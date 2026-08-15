"""MVP medical data model: accounts + persons + medical/access tables

Renames `users` -> `accounts` (migration 0001), introduces persons and the
full DB_MODELS.md MVP schema: identities, RBAC, patients, specialists,
organizations, medical records, documents/versions, encounters, processing
jobs, extractions, access grants and audit logs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.domain.access import AuditAction, GrantStatus
from app.domain.account import AccountStatus, IdentityKind
from app.domain.medical import (
    DocumentStatus,
    DocumentType,
    EncounterStatus,
    EncounterType,
    ExtractionStatus,
    MembershipStatus,
    OrganizationStatus,
    OrganizationType,
    PatientStatus,
    ProcessingJobStatus,
    ProcessingJobType,
    Sex,
    SpecialistStatus,
)
from app.domain.user_type import UserType

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    # --------------------------------------------------------------- accounts
    op.rename_table("users", "accounts")
    op.drop_index(op.f("ix_users_email"), table_name="accounts")
    op.drop_index(op.f("ix_users_phone"), table_name="accounts")
    op.drop_column("accounts", "user_type")

    op.add_column("accounts", sa.Column("email_normalized", sa.String(255), nullable=True))
    op.add_column("accounts", sa.Column("email_verified_at", _ts(), nullable=True))
    op.add_column("accounts", sa.Column("phone_e164", sa.String(32), nullable=True))
    op.add_column("accounts", sa.Column("phone_verified_at", _ts(), nullable=True))
    op.add_column("accounts", sa.Column("last_login_at", _ts(), nullable=True))
    op.add_column("accounts", sa.Column("person_id", _uuid(), nullable=True))
    op.add_column(
        "accounts",
        sa.Column(
            "status",
            sa.Enum(AccountStatus, name="account_status", native_enum=False, length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )

    op.execute(
        "UPDATE accounts SET email_normalized = lower(btrim(email))"
        " WHERE email_normalized IS NULL AND email IS NOT NULL"
    )
    op.execute(
        "UPDATE accounts SET phone_e164 = phone WHERE phone_e164 IS NULL AND phone IS NOT NULL"
    )
    op.create_unique_constraint(
        op.f("uq_accounts_email_normalized"), "accounts", ["email_normalized"]
    )
    op.create_unique_constraint(op.f("uq_accounts_phone_e164"), "accounts", ["phone_e164"])

    # ----------------------------------------------------------------- persons
    op.create_table(
        "persons",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=False),
        sa.Column("middle_name", sa.String(255), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("sex", sa.Enum(Sex, name="sex", native_enum=False, length=16), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_persons")),
    )

    op.execute(
        "INSERT INTO persons (id, first_name, last_name, middle_name, date_of_birth,"
        " sex, created_at, updated_at)"
        " SELECT gen_random_uuid(), '', '', NULL, NULL, NULL, now(), now() FROM accounts"
    )
    op.execute(
        """
        WITH acct AS (SELECT id, row_number() OVER (ORDER BY created_at) AS rn FROM accounts),
             prs  AS (SELECT id, row_number() OVER (ORDER BY created_at) AS rn FROM persons)
        UPDATE accounts a SET person_id = prs.id
        FROM prs JOIN acct ON prs.rn = acct.rn
        WHERE a.id = acct.id
        """
    )
    op.create_unique_constraint(op.f("uq_accounts_person_id"), "accounts", ["person_id"])
    op.create_foreign_key(
        op.f("fk_accounts_person_id_persons"),
        "accounts",
        "persons",
        ["person_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ----------------------------------------------------------- auth_sessions
    op.drop_constraint(op.f("fk_auth_sessions_user_id_users"), "auth_sessions", type_="foreignkey")
    op.alter_column("auth_sessions", "user_id", new_column_name="account_id")
    op.create_foreign_key(
        op.f("fk_auth_sessions_account_id_accounts"),
        "auth_sessions",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------- account_identities
    op.create_table(
        "account_identities",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(IdentityKind, name="identity_kind", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("value_normalized", sa.String(255), nullable=False),
        sa.Column("verified_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_account_identities_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_identities")),
        sa.UniqueConstraint("value_normalized", name="uq_account_identities_value_normalized"),
    )
    op.create_index(
        op.f("ix_account_identities_account_id"),
        "account_identities",
        ["account_id"],
        unique=False,
    )

    # ------------------------------------------------------------------- RBAC
    op.create_table(
        "roles",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_table(
        "account_roles",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=False),
        sa.Column("role_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_account_roles_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_account_roles_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_roles")),
        sa.UniqueConstraint("account_id", "role_id", name="uq_account_roles_account_role"),
    )
    op.create_index(
        op.f("ix_account_roles_account_id"), "account_roles", ["account_id"], unique=False
    )
    op.create_index(op.f("ix_account_roles_role_id"), "account_roles", ["role_id"], unique=False)
    op.create_table(
        "role_permissions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("role_id", _uuid(), nullable=False),
        sa.Column("permission_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name=op.f("fk_role_permissions_permission_id_permissions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_permissions")),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
    )
    op.create_index(
        op.f("ix_role_permissions_role_id"), "role_permissions", ["role_id"], unique=False
    )
    op.create_index(
        op.f("ix_role_permissions_permission_id"),
        "role_permissions",
        ["permission_id"],
        unique=False,
    )

    # ----------------------------------------------------------------- patient
    op.create_table(
        "patients",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("person_id", _uuid(), nullable=False),
        sa.Column("medical_record_number", sa.String(64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(PatientStatus, name="patient_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name=op.f("fk_patients_person_id_persons"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("person_id", name="uq_patients_person_id"),
    )

    # -------------------------------------------------------------- specialist
    op.create_table(
        "specialists",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("person_id", _uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(SpecialistStatus, name="specialist_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name=op.f("fk_specialists_person_id_persons"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specialists")),
    )
    op.create_index(op.f("ix_specialists_person_id"), "specialists", ["person_id"], unique=False)
    op.create_table(
        "specialties",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specialties")),
        sa.UniqueConstraint("code", name="uq_specialties_code"),
    )
    op.create_table(
        "specialist_specialties",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("specialist_id", _uuid(), nullable=False),
        sa.Column("specialty_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["specialist_id"],
            ["specialists.id"],
            name=op.f("fk_specialist_specialties_specialist_id_specialists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["specialty_id"],
            ["specialties.id"],
            name=op.f("fk_specialist_specialties_specialty_id_specialties"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specialist_specialties")),
        sa.UniqueConstraint(
            "specialist_id", "specialty_id", name="uq_specialist_specialties_specialist_specialty"
        ),
    )
    op.create_index(
        op.f("ix_specialist_specialties_specialist_id"),
        "specialist_specialties",
        ["specialist_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_specialist_specialties_specialty_id"),
        "specialist_specialties",
        ["specialty_id"],
        unique=False,
    )

    # ------------------------------------------------------------ organizations
    op.create_table(
        "organizations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "type",
            sa.Enum(OrganizationType, name="organization_type", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(OrganizationStatus, name="organization_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=False),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(MembershipStatus, name="membership_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("joined_at", _ts(), nullable=False),
        sa.Column("left_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_memberships_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_organization_memberships_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_memberships")),
        sa.UniqueConstraint(
            "organization_id", "account_id", name="uq_organization_memberships_org_account"
        ),
    )
    op.create_index(
        op.f("ix_organization_memberships_organization_id"),
        "organization_memberships",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_memberships_account_id"),
        "organization_memberships",
        ["account_id"],
        unique=False,
    )

    # ---------------------------------------------------------- medical record
    op.create_table(
        "medical_records",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("patient_id", _uuid(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_medical_records_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medical_records")),
        sa.UniqueConstraint("patient_id", name="uq_medical_records_patient_id"),
    )

    # --------------------------------------------------------------- encounters
    op.create_table(
        "encounters",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("medical_record_id", _uuid(), nullable=False),
        sa.Column("specialist_id", _uuid(), nullable=True),
        sa.Column("organization_id", _uuid(), nullable=True),
        sa.Column(
            "type",
            sa.Enum(EncounterType, name="encounter_type", native_enum=False, length=32),
            nullable=False,
            server_default=sa.text("'consultation'"),
        ),
        sa.Column(
            "status",
            sa.Enum(EncounterStatus, name="encounter_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'scheduled'"),
        ),
        sa.Column("started_at", _ts(), nullable=False),
        sa.Column("ended_at", _ts(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["medical_record_id"],
            ["medical_records.id"],
            name=op.f("fk_encounters_medical_record_id_medical_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["specialist_id"],
            ["specialists.id"],
            name=op.f("fk_encounters_specialist_id_specialists"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_encounters_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_encounters")),
    )
    op.create_index(
        op.f("ix_encounters_medical_record_id"), "encounters", ["medical_record_id"], unique=False
    )
    op.create_index(
        op.f("ix_encounters_specialist_id"), "encounters", ["specialist_id"], unique=False
    )
    op.create_index(
        op.f("ix_encounters_organization_id"), "encounters", ["organization_id"], unique=False
    )

    # ---------------------------------------------------------------- documents
    op.create_table(
        "documents",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("medical_record_id", _uuid(), nullable=False),
        sa.Column("encounter_id", _uuid(), nullable=True),
        sa.Column(
            "document_type",
            sa.Enum(DocumentType, name="document_type", native_enum=False, length=32),
            nullable=False,
            server_default=sa.text("'other'"),
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column(
            "status",
            sa.Enum(DocumentStatus, name="document_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'uploaded'"),
        ),
        sa.Column("uploaded_by_account_id", _uuid(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["medical_record_id"],
            ["medical_records.id"],
            name=op.f("fk_documents_medical_record_id_medical_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["encounter_id"],
            ["encounters.id"],
            name=op.f("fk_documents_encounter_id_encounters"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_account_id"],
            ["accounts.id"],
            name=op.f("fk_documents_uploaded_by_account_id_accounts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        op.f("ix_documents_medical_record_id"), "documents", ["medical_record_id"], unique=False
    )
    op.create_index(op.f("ix_documents_encounter_id"), "documents", ["encounter_id"], unique=False)
    op.create_index(
        op.f("ix_documents_uploaded_by_account_id"),
        "documents",
        ["uploaded_by_account_id"],
        unique=False,
    )

    op.create_table(
        "document_versions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("document_id", _uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(256), nullable=True),
        sa.Column("created_by_account_id", _uuid(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["accounts.id"],
            name=op.f("fk_document_versions_created_by_account_id_accounts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "version", name="uq_document_versions_document_version"),
    )
    op.create_index(
        op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False
    )

    # ------------------------------------------------------------- processing
    op.create_table(
        "document_processing_jobs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("document_id", _uuid(), nullable=False),
        sa.Column("document_version_id", _uuid(), nullable=True),
        sa.Column(
            "job_type",
            sa.Enum(ProcessingJobType, name="processing_job_type", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                ProcessingJobStatus, name="processing_job_status", native_enum=False, length=16
            ),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", _ts(), nullable=True),
        sa.Column("finished_at", _ts(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_processing_jobs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_document_processing_jobs_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_processing_jobs")),
    )
    op.create_index(
        op.f("ix_document_processing_jobs_document_id"),
        "document_processing_jobs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_processing_jobs_document_version_id"),
        "document_processing_jobs",
        ["document_version_id"],
        unique=False,
    )

    # ------------------------------------------------------------- extraction
    op.create_table(
        "document_extractions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("document_id", _uuid(), nullable=False),
        sa.Column("document_version_id", _uuid(), nullable=True),
        sa.Column("schema_name", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(ExtractionStatus, name="extraction_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_extractions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_document_extractions_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_extractions")),
    )
    op.create_index(
        op.f("ix_document_extractions_document_id"),
        "document_extractions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_extractions_document_version_id"),
        "document_extractions",
        ["document_version_id"],
        unique=False,
    )

    # ------------------------------------------------------------- access grant
    op.create_table(
        "patient_access_grants",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("patient_id", _uuid(), nullable=False),
        sa.Column("account_id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=True),
        sa.Column("can_view_documents", sa.Boolean(), nullable=False),
        sa.Column("can_upload_documents", sa.Boolean(), nullable=False),
        sa.Column("can_view_extractions", sa.Boolean(), nullable=False),
        sa.Column("can_view_analytics", sa.Boolean(), nullable=False),
        sa.Column("can_create_encounters", sa.Boolean(), nullable=False),
        sa.Column("can_edit_medical_data", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(GrantStatus, name="grant_status", native_enum=False, length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("granted_at", _ts(), nullable=False),
        sa.Column("expires_at", _ts(), nullable=True),
        sa.Column("granted_by_account_id", _uuid(), nullable=True),
        sa.Column("access_reason", sa.String(64), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_patient_access_grants_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_patient_access_grants_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_patient_access_grants_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_account_id"],
            ["accounts.id"],
            name=op.f("fk_patient_access_grants_granted_by_account_id_accounts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient_access_grants")),
    )
    op.create_index(
        op.f("ix_patient_access_grants_patient_id"),
        "patient_access_grants",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_patient_access_grants_account_id"),
        "patient_access_grants",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_patient_access_grants_organization_id"),
        "patient_access_grants",
        ["organization_id"],
        unique=False,
    )

    # ---------------------------------------------------------------- audit log
    op.create_table(
        "audit_logs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("actor_account_id", _uuid(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(AuditAction, name="audit_action", native_enum=False, length=64),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", _uuid(), nullable=True),
        sa.Column("patient_id", _uuid(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("user_agent", sa.String(512), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["accounts.id"],
            name=op.f("fk_audit_logs_actor_account_id_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_audit_logs_patient_id_patients"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        op.f("ix_audit_logs_actor_account_id"), "audit_logs", ["actor_account_id"], unique=False
    )
    op.create_index(op.f("ix_audit_logs_patient_id"), "audit_logs", ["patient_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_patient_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_account_id"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(
        op.f("ix_patient_access_grants_organization_id"), table_name="patient_access_grants"
    )
    op.drop_index(op.f("ix_patient_access_grants_account_id"), table_name="patient_access_grants")
    op.drop_index(op.f("ix_patient_access_grants_patient_id"), table_name="patient_access_grants")
    op.drop_table("patient_access_grants")

    op.drop_index(
        op.f("ix_document_extractions_document_version_id"), table_name="document_extractions"
    )
    op.drop_index(op.f("ix_document_extractions_document_id"), table_name="document_extractions")
    op.drop_table("document_extractions")

    op.drop_index(
        op.f("ix_document_processing_jobs_document_version_id"),
        table_name="document_processing_jobs",
    )
    op.drop_index(
        op.f("ix_document_processing_jobs_document_id"), table_name="document_processing_jobs"
    )
    op.drop_table("document_processing_jobs")

    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_table("document_versions")

    op.drop_index(op.f("ix_documents_uploaded_by_account_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_encounter_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_medical_record_id"), table_name="documents")
    op.drop_table("documents")

    op.drop_index(op.f("ix_encounters_organization_id"), table_name="encounters")
    op.drop_index(op.f("ix_encounters_specialist_id"), table_name="encounters")
    op.drop_index(op.f("ix_encounters_medical_record_id"), table_name="encounters")
    op.drop_table("encounters")

    op.drop_table("medical_records")

    op.drop_index(
        op.f("ix_organization_memberships_account_id"), table_name="organization_memberships"
    )
    op.drop_index(
        op.f("ix_organization_memberships_organization_id"), table_name="organization_memberships"
    )
    op.drop_table("organization_memberships")
    op.drop_table("organizations")

    op.drop_index(
        op.f("ix_specialist_specialties_specialty_id"), table_name="specialist_specialties"
    )
    op.drop_index(
        op.f("ix_specialist_specialties_specialist_id"), table_name="specialist_specialties"
    )
    op.drop_table("specialist_specialties")
    op.drop_table("specialties")
    op.drop_index(op.f("ix_specialists_person_id"), table_name="specialists")
    op.drop_table("specialists")

    op.drop_table("patients")

    op.drop_index(op.f("ix_role_permissions_permission_id"), table_name="role_permissions")
    op.drop_index(op.f("ix_role_permissions_role_id"), table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_index(op.f("ix_account_roles_role_id"), table_name="account_roles")
    op.drop_index(op.f("ix_account_roles_account_id"), table_name="account_roles")
    op.drop_table("account_roles")
    op.drop_table("permissions")
    op.drop_table("roles")

    op.drop_index(op.f("ix_account_identities_account_id"), table_name="account_identities")
    op.drop_table("account_identities")

    # auth_sessions back to users.user_id
    op.drop_constraint(
        op.f("fk_auth_sessions_account_id_accounts"), "auth_sessions", type_="foreignkey"
    )
    op.alter_column("auth_sessions", "account_id", new_column_name="user_id")
    op.create_foreign_key(
        op.f("fk_auth_sessions_user_id_users"),
        "auth_sessions",
        "accounts",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(op.f("fk_accounts_person_id_persons"), "accounts", type_="foreignkey")
    op.drop_constraint(op.f("uq_accounts_person_id"), "accounts", type_="unique")
    op.execute(
        "DELETE FROM persons WHERE id NOT IN (SELECT person_id FROM accounts WHERE person_id IS NOT NULL)"  # noqa: E501
    )
    op.drop_table("persons")

    op.drop_constraint(op.f("uq_accounts_phone_e164"), "accounts", type_="unique")
    op.drop_constraint(op.f("uq_accounts_email_normalized"), "accounts", type_="unique")
    op.drop_column("accounts", "status")
    op.drop_column("accounts", "person_id")
    op.drop_column("accounts", "last_login_at")
    op.drop_column("accounts", "phone_verified_at")
    op.drop_column("accounts", "phone_e164")
    op.drop_column("accounts", "email_verified_at")
    op.drop_column("accounts", "email_normalized")

    op.add_column(
        "accounts",
        sa.Column(
            "user_type",
            sa.Enum(UserType, name="user_type", native_enum=False, length=32),
            nullable=False,
            server_default="user",
        ),
    )
    op.create_index(op.f("ix_users_phone"), "accounts", ["phone"], unique=True)
    op.create_index(op.f("ix_users_email"), "accounts", ["email"], unique=True)
    op.rename_table("accounts", "users")

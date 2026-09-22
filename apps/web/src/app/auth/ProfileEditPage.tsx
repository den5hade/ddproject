import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useController, useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useMyPatient } from "@/features/auth/hooks";
import {
  fromPerson,
  maskDateOfBirth,
  profileFormSchema,
  toPersonUpdate,
  type ProfileFormValues,
} from "@/features/patients/schemas";
import { useUpdateMyPerson } from "@/features/patients/hooks";
import { strings } from "@/lib/i18n/strings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SelectDropdown, type SelectOption } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

/*
 * Profile personal-data form (plan §6.8): RHF+zod → PATCH /patients/me →
 * invalidation → toast «Изменения сохранены» [SG §49], then back to the
 * profile overview. Reached from /profile and /medical-record.
 */

const sexOptions: SelectOption[] = [
  { value: "male", label: strings.profile.sexMale },
  { value: "female", label: strings.profile.sexFemale },
  { value: "unspecified", label: strings.profile.sexUnspecified },
];

export function ProfileEditPage() {
  const patient = useMyPatient();
  const updatePerson = useUpdateMyPerson();
  const navigate = useNavigate();

  const {
    register,
    handleSubmit,
    reset,
    control,
    setError,
    formState: { errors },
  } = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    defaultValues: fromPerson({}),
    shouldUnregister: true,
  });

  const {
    field: { value: sexValue, onChange: onSexChange },
  } = useController({ control, name: "sex" });

  // Sync defaults once patient data arrives
  useEffect(() => {
    if (patient.data) {
      reset(fromPerson(patient.data.person));
    }
  }, [patient.data, reset]);

  const submit = handleSubmit((values) => {
    updatePerson.mutate(toPersonUpdate(values), {
      onSuccess: () => {
        toast(strings.profile.savedToast);
        navigate("/profile");
      },
      onError: (error) => {
        // Surface field errors from 422 loc mapping; generic otherwise
        const fields = (
          error as { fields?: Record<string, string> | undefined }
        ).fields;
        let matched = false;
        for (const [field, message] of Object.entries(fields ?? {})) {
          if (field in profileFormSchema.shape) {
            setError(field as keyof ProfileFormValues, { message });
            matched = true;
          }
        }
        if (!matched && error instanceof Error && error.message) {
          setError("root", { message: error.message });
        }
      },
    });
  });

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-[28px] font-semibold leading-tight text-ink lg:text-[30px]">
          {strings.profile.editTitle}
        </h1>
        <p className="mt-1 text-[15px] text-ink-secondary">
          {strings.profile.editSubtitle}
        </p>
      </header>

      {patient.isPending ? (
        <div className="space-y-4" aria-hidden="true">
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-16 w-full rounded-lg" />
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="flex max-w-[480px] flex-col gap-4">
          <Field label={strings.profile.name} htmlFor="name" error={errors.name?.message}>
            <Input id="name" autoComplete="name" {...register("name")} />
          </Field>

          <Field
            label={strings.profile.dateOfBirth}
            htmlFor="date_of_birth"
            error={errors.date_of_birth?.message}
          >
            <Input
              id="date_of_birth"
              type="text"
              inputMode="numeric"
              autoComplete="bday"
              maxLength={10}
              placeholder={strings.profile.dateOfBirthPlaceholder}
              {...register("date_of_birth", {
                onChange: (event) => {
                  event.target.value = maskDateOfBirth(event.target.value);
                },
              })}
            />
          </Field>

          <Field label={strings.profile.sex} htmlFor="sex" error={errors.sex?.message}>
            <SelectDropdown
              id="sex"
              label={strings.profile.sex}
              value={sexValue}
              options={sexOptions}
              placeholder={strings.profile.sexNotSet}
              disabled={updatePerson.isPending}
              onChange={onSexChange}
            />
          </Field>

          <Field label={strings.profile.city} htmlFor="city" error={errors.city?.message}>
            <Input id="city" autoComplete="address-level2" {...register("city")} />
          </Field>

          <Field
            label={strings.profile.profession}
            htmlFor="profession"
            error={errors.profession?.message}
          >
            <Input id="profession" {...register("profession")} />
          </Field>

          <div className="flex gap-4">
            <Field label={strings.profile.height} htmlFor="height" error={errors.height?.message}>
              <Input id="height" type="text" inputMode="decimal" {...register("height")} />
            </Field>

            <Field label={strings.profile.weight} htmlFor="weight" error={errors.weight?.message}>
              <Input id="weight" type="text" inputMode="decimal" {...register("weight")} />
            </Field>
          </div>

          {errors.root?.message && (
            <p role="alert" className="text-sm text-danger">
              {errors.root.message}
            </p>
          )}

          <div className="mt-2 flex items-center justify-between gap-4">
            <Button type="submit" disabled={updatePerson.isPending}>
              {updatePerson.isPending ? strings.profile.saving : strings.profile.save}
            </Button>
            <p className="text-xs text-ink-muted">{strings.profile.savedHint}</p>
          </div>

          <Link
            to="/profile"
            className="shrink-0 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {strings.profile.backToProfile}
          </Link>
        </form>
      )}
    </div>
  );
}

function Field({
  label,
  htmlFor,
  error,
  children,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
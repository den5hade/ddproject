import asyncio
import json
import logging
import logging.handlers
import os
import sys
import time
from typing import Any

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


def setup_logger(
    name: str = "ddp_backend",
    level: int = logging.INFO,
    log_to_file: bool = False,
    log_dir: str = "logs",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Setup and configure application logger.

    Args:
        name: Logger name
        level: Logging level (default: INFO)
        log_to_file: Enable file logging
        log_dir: Directory for log files
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup files to keep

    Returns:
        Configured logger instance
    """
    _ = max_bytes
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Кастомный форматтер
    class ClientFormatter(logging.Formatter):
        def format(self, record):
            if not hasattr(record, "client"):
                record.client = "unknown"
            return super().format(record)

    # Затем:
    formatter = ClientFormatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(client)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler with rotation (if enabled)
    if log_to_file:
        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)

        # Use TimedRotatingFileHandler for date-based naming
        log_file_path = os.path.join(log_dir, "dbl.log")
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file_path,
            when="midnight",  # Rotate at midnight
            interval=1,  # Every 1 day
            backupCount=backup_count,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Global logger instance
logger = setup_logger(
    name=settings.app_name,
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    log_to_file=settings.log_to_file,
    log_dir=settings.log_dir,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests and responses to the logger service."""

    def __init__(self, app):
        super().__init__(app)

        self.enabled = settings.enable_request_logging
        self.log_request_body = settings.log_request_body
        self.log_response_body = settings.log_response_body  # Disabled by default for performance
        self.max_body_size = settings.max_log_body_size

        # Paths to exclude from logging (health checks, metrics, etc.)
        self.excluded_paths = {
            "/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
            "/",  # Root endpoint
        }

    async def dispatch(self, request: Request, call_next):
        """Process the request and log it."""
        if not self.enabled:
            return await call_next(request)

        # Skip logging for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        start_time = time.time()

        # Capture request data
        request_data = await self._capture_request_data(request)

        # Process the request
        try:
            response = await call_next(request)
        except Exception:
            processing_time = int((time.time() - start_time) * 1000)
            logger.exception(
                json.dumps(
                    {
                        "method": request_data["method"],
                        "path": request_data["path"],
                        "query_params": request_data["query_params"],
                        "processing_time_ms": processing_time,
                        "error": "Unhandled request exception",
                    },
                    ensure_ascii=False,
                ),
                extra={"client": request_data.get("client_ip") or "unknown"},
            )
            raise

        # Calculate processing time
        processing_time = int((time.time() - start_time) * 1000)  # Convert to milliseconds

        # Capture response data
        response_data = await self._capture_response_data(response)

        # Create log entry asynchronously (fire and forget)
        asyncio.create_task(
            self._log_request_response(
                request, response, request_data, response_data, processing_time
            )
        )

        return response

    async def _capture_request_data(self, request: Request) -> dict[str, Any]:
        """Capture request data for logging."""
        data = {
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params) if request.query_params else None,
            "headers": dict(request.headers),
            "client_ip": self._get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "request_body": None,
        }

        # Capture request body if enabled and content type is appropriate
        if self.log_request_body and self._should_log_body(request.headers.get("content-type")):
            try:
                body = await request.body()
                if body and len(body) <= self.max_body_size:
                    # Try to decode as JSON first, then as text
                    try:
                        body_json = json.loads(body.decode("utf-8"))
                        # Mask sensitive fields in JSON body
                        masked_body = self._mask_sensitive_data(body_json)
                        data["request_body"] = json.dumps(masked_body)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        try:
                            body_text = body.decode("utf-8")
                            # Mask sensitive data in text body (form data, etc.)
                            data["request_body"] = self._mask_sensitive_text(body_text)
                        except UnicodeDecodeError:
                            data["request_body"] = f"<binary data: {len(body)} bytes>"
                elif len(body) > self.max_body_size:
                    data["request_body"] = f"<body too large: {len(body)} bytes>"
            except Exception as e:
                data["request_body"] = f"<error reading body: {str(e)}>"

        return data

    async def _capture_response_data(self, response: Response) -> dict[str, Any]:
        """Capture response data for logging."""
        data = {"status_code": response.status_code, "response_body": None}

        # Capture response body if enabled
        if self.log_response_body and hasattr(response, "body"):
            try:
                if isinstance(response, StreamingResponse):
                    # For streaming responses, we can't easily capture the body
                    data["response_body"] = "<streaming response>"
                else:
                    body = response.body
                    if body and len(body) <= self.max_body_size:
                        # Try to decode as JSON first, then as text
                        try:
                            # Convert body to bytes if it's not already
                            body_bytes = body if isinstance(body, bytes) else bytes(body)
                            response_json = json.loads(body_bytes.decode("utf-8"))
                            # Mask sensitive fields in JSON response (like tokens)
                            masked_response = self._mask_sensitive_data(response_json)
                            data["response_body"] = json.dumps(masked_response)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            try:
                                body_bytes = body if isinstance(body, bytes) else bytes(body)
                                response_text = body_bytes.decode("utf-8")
                                # Mask sensitive data in text response
                                data["response_body"] = self._mask_sensitive_text(response_text)
                            except UnicodeDecodeError:
                                data["response_body"] = f"<binary data: {len(body)} bytes>"
                    elif len(body) > self.max_body_size:
                        data["response_body"] = f"<body too large: {len(body)} bytes>"
            except Exception as e:
                data["response_body"] = f"<error reading response body: {str(e)}>"

        return data

    async def _log_request_response(
        self,
        request: Request,
        response: Response,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
        processing_time: int,
    ) -> None:
        """Write a structured request/response log entry."""
        log_payload = {
            "method": request.method,
            "path": request.url.path,
            "query_params": request_data["query_params"],
            "status_code": response.status_code,
            "processing_time_ms": processing_time,
            "headers": self._filter_sensitive_headers(request_data["headers"]),
            "user_agent": request_data["user_agent"],
        }

        if request_data["request_body"] is not None:
            log_payload["request_body"] = request_data["request_body"]

        if response_data["response_body"] is not None:
            log_payload["response_body"] = response_data["response_body"]

        log_method = logger.info
        if response.status_code >= 500:
            log_method = logger.error
        elif response.status_code >= 400:
            log_method = logger.warning

        log_method(
            json.dumps(log_payload, ensure_ascii=False),
            extra={"client": request_data.get("client_ip") or "unknown"},
        )

    def _get_client_ip(self, request: Request) -> str | None:
        """Extract client IP from request headers."""
        # Check for forwarded headers first (for reverse proxies)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if hasattr(request, "client") and request.client:
            return request.client.host

        return None

    def _should_log_body(self, content_type: str | None) -> bool:
        """Determine if we should log the request/response body based on content type."""
        if not content_type:
            return False

        # Log JSON and text content types
        loggable_types = [
            "application/json",
            "application/x-www-form-urlencoded",
            "text/plain",
            "text/html",
            "text/xml",
            "application/xml",
        ]

        return any(content_type.startswith(t) for t in loggable_types)

    def _filter_sensitive_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Filter out sensitive headers from logging."""
        sensitive_headers = {
            "authorization",
            "cookie",
            "x-api-key",
            "x-auth-token",
            "x-access-token",
        }

        filtered = {}
        for key, value in headers.items():
            if key.lower() in sensitive_headers:
                filtered[key] = "<redacted>"
            else:
                filtered[key] = value

        return filtered

    def _mask_sensitive_data(self, data: Any) -> Any:
        """Recursively mask sensitive data in JSON objects."""
        if isinstance(data, dict):
            masked_data = {}
            for key, value in data.items():
                if self._is_sensitive_field(key):
                    masked_data[key] = self._mask_value(value)
                elif isinstance(value, (dict, list)):
                    masked_data[key] = self._mask_sensitive_data(value)
                else:
                    masked_data[key] = value
            return masked_data
        elif isinstance(data, list):
            return [self._mask_sensitive_data(item) for item in data]
        else:
            return data

    def _is_sensitive_field(self, field_name: str) -> bool:
        """Check if a field name contains sensitive data."""
        sensitive_fields = {
            # Password related
            "password",
            "passwd",
            "pwd",
            "pass",
            "passphrase",
            "confirm_password",
            "new_password",
            "old_password",
            "current_password",
            "password_confirmation",
            "password_confirm",
            "repeat_password",
            # Authentication tokens
            "token",
            "access_token",
            "refresh_token",
            "auth_token",
            "bearer_token",
            "jwt",
            "jwt_token",
            "session_token",
            "csrf_token",
            "xsrf_token",
            # API keys and secrets
            "secret",
            "api_key",
            "apikey",
            "api_secret",
            "client_secret",
            "private_key",
            "public_key",
            "encryption_key",
            "signing_key",
            # Authentication
            "auth",
            "authorization",
            "credential",
            "credentials",
            "session",
            "session_id",
            "cookie",
            "cookies",
            # Personal information
            "pin",
            "ssn",
            "email",
            "phone",
            "name",
            "social_security",
            "social_security_number",
            "credit_card",
            "card_number",
            "card_num",
            "cvv",
            "cvc",
            "cvv2",
            "bank_account",
            "account_number",
            "routing_number",
            # Other sensitive data
            "otp",
            "verification_code",
            "reset_code",
            "activation_code",
            "code",
            "recipient",
            "security_question",
            "security_answer",
            "backup_codes",
        }

        field_lower = field_name.lower()
        return any(sensitive in field_lower for sensitive in sensitive_fields)

    def _mask_value(self, value: Any) -> Any:
        """Mask a sensitive value."""
        if value is None:
            return None

        return "<redacted>"

    def _mask_sensitive_text(self, text: str) -> str:
        """Mask sensitive data in text format (form data, query strings, etc.)."""
        import re

        # Common patterns for form data and query strings
        patterns = [
            # password=value or password:value
            (r"(password[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(passwd[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(pwd[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            # token=value or token:value
            (r"(token[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(secret[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(key[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            # API key patterns
            (r"(api[_-]?key[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(access[_-]?token[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            # PII patterns
            (r"(email[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(phone[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(recipient[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(code[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            (r"(name[=:]\s*)([^&\s\n\r]+)", r"\1***"),
            # Credit card patterns (basic)
            (r"(\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4})", r"****-****-****-****"),
        ]

        masked_text = text
        for pattern, replacement in patterns:
            masked_text = re.sub(pattern, replacement, masked_text, flags=re.IGNORECASE)

        return masked_text

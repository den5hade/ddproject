import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { normalizeIdentity } from "../schemas";
import { identityFormSchema, type IdentityFormValues } from "../schemas";
import { strings } from "@/lib/i18n/strings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface IdentityFormProps {
  pending: boolean;
  serverError?: string | null;
  onSubmit: (identity: string) => void;
}

/*
 * SG §25–26: simple column form, no giant card.
 * SG §13: label → input 8px, inputs stacked with 16px.
 */
export function IdentityForm({
  pending,
  serverError,
  onSubmit,
}: IdentityFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<IdentityFormValues>({
    resolver: zodResolver(identityFormSchema),
    defaultValues: { identity: "" },
  });

  const submit = handleSubmit(({ identity }) => {
    onSubmit(normalizeIdentity(identity));
  });

  const errorMessage = errors.identity?.message ?? serverError ?? null;

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Input
          id="identity"
          autoComplete="username"
          inputMode="email"
          aria-label={strings.login.identityLabel}
          placeholder={strings.login.identityPlaceholder}
          aria-invalid={errorMessage ? true : undefined}
          aria-describedby={errorMessage ? "identity-error" : undefined}
          {...register("identity")}
        />
        {errorMessage && (
          <p id="identity-error" role="alert" className="text-sm text-danger">
            {errorMessage}
          </p>
        )}
      </div>

      <Button type="submit" disabled={pending} className="w-full">
        {pending ? strings.login.submitting : strings.login.submit}
      </Button>
    </form>
  );
}

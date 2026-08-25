import { useRef, type ClipboardEvent, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (code: string) => void;
  disabled?: boolean;
}

const LENGTH = 6;

/*
 * Six-cell OTP input: auto-advance, backspace to previous cell,
 * full-code paste distribution (plan §6.2).
 * Value is a compact string of digits only (max LENGTH).
 */
export function OtpInput({
  value,
  onChange,
  onComplete,
  disabled,
}: OtpInputProps) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  const focusCell = (index: number) => {
    const clamped = Math.max(0, Math.min(LENGTH - 1, index));
    const el = refs.current[clamped];
    if (el) {
      el.focus();
      el.select();
    }
  };

  /** Digits shown per cell: compact value padded to LENGTH. */
  const cells = Array.from(
    { length: LENGTH },
    (_, i) => value[i] ?? "",
  );

  /** Cell index is the visual position; digits before it = min(index, value.length). */
  const replaceAt = (visualIndex: number, insertedDigits: string) => {
    const before = value.slice(0, Math.min(visualIndex, value.length));
    const after = value.slice(Math.min(visualIndex + 1, value.length));
    return (before + insertedDigits + after)
      .replace(/\D/g, "")
      .slice(0, LENGTH);
  };

  const handleChange = (
    event: React.ChangeEvent<HTMLInputElement>,
    index: number,
  ) => {
    const digits = event.target.value.replace(/\D/g, "");
    if (!digits) {
      // Cell cleared (e.g. select + delete): remove that digit from value
      onChange(value.slice(0, Math.min(index, value.length)) + value.slice(Math.min(index + 1, value.length)));
      return;
    }
    const next = replaceAt(index, digits);
    onChange(next);
    if (next.length === LENGTH) {
      onComplete?.(next);
    } else {
      focusCell(next.length);
    }
  };

  const handleKeyDown = (
    event: KeyboardEvent<HTMLInputElement>,
    index: number,
  ) => {
    if (event.key === "Backspace") {
      event.preventDefault();
      if (value[index]) {
        // Remove digit at this position
        onChange(value.slice(0, index) + value.slice(index + 1));
      } else if (index > 0) {
        // Empty cell → remove previous digit and step back
        onChange(value.slice(0, index - 1) + value.slice(index));
        focusCell(index - 1);
      }
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusCell(index - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      focusCell(index + 1);
    }
  };

  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    event.preventDefault();
    const digits = event.clipboardData
      .getData("text")
      .replace(/\D/g, "")
      .slice(0, LENGTH);
    onChange(digits);
    focusCell(digits.length);
    if (digits.length === LENGTH) onComplete?.(digits);
  };

  return (
    <div role="group" aria-label="Код подтверждения" className="flex gap-2">
      {cells.map((digit, index) => (
        <input
          key={index}
          ref={(el) => {
            refs.current[index] = el;
          }}
          value={digit}
          disabled={disabled}
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          aria-label={`Цифра ${index + 1} из ${LENGTH}`}
          className={cn(
            "h-12 w-11 rounded-lg border border-border-input bg-surface text-center text-lg font-medium text-ink",
            "transition-colors duration-150 ease-out",
            "focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20",
            "disabled:bg-surface-muted disabled:text-ink-disabled",
          )}
          onChange={(e) => handleChange(e, index)}
          onKeyDown={(e) => handleKeyDown(e, index)}
          onPaste={handlePaste}
          onFocus={(e) => e.target.select()}
        />
      ))}
    </div>
  );
}

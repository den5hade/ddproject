import {
  createContext,
  useContext,
  useId,
  useState,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

/*
 * Minimal accessible tabs (WAI-ARIA pattern): roving selection via
 * aria-selected/aria-controls, arrow-key navigation. Enough for the
 * two-tab document viewer; swap for radix Tabs later if needs grow.
 */

interface TabsContextValue {
  value: string;
  setValue: (value: string) => void;
  baseId: string;
}

const TabsContext = createContext<TabsContextValue | null>(null);

export function Tabs({
  defaultValue,
  children,
  className,
}: {
  defaultValue: string;
  children: ReactNode;
  className?: string;
}) {
  const [value, setValue] = useState(defaultValue);
  const baseId = useId();
  return (
    <TabsContext.Provider value={{ value, setValue, baseId }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ labels }: { labels: Record<string, string> }) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("Tabs.List must be used inside Tabs");
  return (
    <div
      role="tablist"
      aria-label="Просмотр документа"
      className="flex gap-1 rounded-lg border border-border bg-surface-muted p-1"
      onKeyDown={(event) => {
        const keys = Object.keys(labels);
        const index = keys.indexOf(ctx.value);
        if (event.key === "ArrowRight") {
          event.preventDefault();
          ctx.setValue(keys[(index + 1) % keys.length]!);
        } else if (event.key === "ArrowLeft") {
          event.preventDefault();
          ctx.setValue(keys[(index - 1 + keys.length) % keys.length]!);
        }
      }}
    >
      {Object.entries(labels).map(([key, label]) => (
        <button
          key={key}
          type="button"
          role="tab"
          id={`${ctx.baseId}-tab-${key}`}
          aria-selected={ctx.value === key}
          aria-controls={`${ctx.baseId}-panel-${key}`}
          tabIndex={ctx.value === key ? 0 : -1}
          onClick={() => ctx.setValue(key)}
          className={cn(
            "flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150 ease-out",
            ctx.value === key
              ? "bg-surface text-ink"
              : "text-ink-secondary hover:text-ink",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({
  value,
  children,
}: {
  value: string;
  children: ReactNode;
}) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("TabPanel must be used inside Tabs");
  if (ctx.value !== value) return null;
  return (
    <div
      role="tabpanel"
      id={`${ctx.baseId}-panel-${value}`}
      aria-labelledby={`${ctx.baseId}-tab-${value}`}
      tabIndex={0}
    >
      {children}
    </div>
  );
}

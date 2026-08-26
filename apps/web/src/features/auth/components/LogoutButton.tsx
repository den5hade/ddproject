import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";

/* Tertiary placement, no confirmation required (plan §6.8). */
export function LogoutButton({ onLogout }: { onLogout: () => void }) {
  return (
    <Button variant="ghost" onClick={onLogout} className="text-ink-secondary">
      <LogOut size={16} strokeWidth={2} />
      Выйти
    </Button>
  );
}

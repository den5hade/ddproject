import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { strings } from "@/lib/i18n/strings";

/* Round icon-only action in the profile header (plan §6.8); aria-label keeps it accessible. */
export function LogoutButton({ onLogout }: { onLogout: () => void }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={strings.profile.logout}
      onClick={onLogout}
      className="rounded-full text-ink-secondary hover:text-ink"
    >
      <LogOut size={20} strokeWidth={2} />
    </Button>
  );
}
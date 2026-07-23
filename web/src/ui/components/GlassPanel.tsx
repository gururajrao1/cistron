import type { ReactNode } from "react";
import { clsx, panelClasses, type PanelVariant, tw } from "../design_system";

type GlassPanelProps = {
  title?: string;
  actions?: ReactNode;
  variant?: PanelVariant;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
};

export function GlassPanel({
  title,
  actions,
  variant = "glass",
  className,
  bodyClassName,
  children,
}: GlassPanelProps) {
  return (
    <section className={clsx(panelClasses(variant), "flex flex-col overflow-hidden", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-[rgba(148,163,184,0.12)] px-3 py-2">
          {title ? <h2 className={tw.title}>{title}</h2> : <span />}
          {actions}
        </header>
      )}
      <div className={clsx("flex-1", bodyClassName ?? "p-3")}>{children}</div>
    </section>
  );
}

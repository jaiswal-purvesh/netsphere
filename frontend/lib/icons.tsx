// Small, self-contained line-icon set for the shell nav and page chrome.
// Deliberately built from basic primitives (rect/circle/line/simple paths)
// rather than a large external icon library or memorized icon-font path
// data, so every glyph renders exactly as intended at 18-20px.

type IconProps = { className?: string };
const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export function IconDashboard({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1.3" />
      <rect x="11" y="2.5" width="6.5" height="4" rx="1.3" />
      <rect x="11" y="8.5" width="6.5" height="9" rx="1.3" />
      <rect x="2.5" y="11" width="6.5" height="6.5" rx="1.3" />
    </svg>
  );
}

export function IconServer({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <rect x="2.5" y="3" width="15" height="5.5" rx="1.2" />
      <rect x="2.5" y="11.5" width="15" height="5.5" rx="1.2" />
      <circle cx="6" cy="5.75" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="6" cy="14.25" r="0.9" fill="currentColor" stroke="none" />
      <line x1="9.5" y1="5.75" x2="14.5" y2="5.75" />
      <line x1="9.5" y1="14.25" x2="14.5" y2="14.25" />
    </svg>
  );
}

export function IconDatabase({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <ellipse cx="10" cy="4.5" rx="6.5" ry="2.2" />
      <path d="M3.5 4.5v11c0 1.2 2.9 2.2 6.5 2.2s6.5-1 6.5-2.2v-11" />
      <path d="M3.5 10c0 1.2 2.9 2.2 6.5 2.2s6.5-1 6.5-2.2" />
    </svg>
  );
}

export function IconCalculator({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <rect x="3.5" y="2.5" width="13" height="15" rx="1.5" />
      <line x1="6" y1="5.5" x2="14" y2="5.5" />
      <line x1="6" y1="9" x2="6" y2="9" />
      <line x1="10" y1="9" x2="10" y2="9" />
      <line x1="14" y1="9" x2="14" y2="9" />
      <line x1="6" y1="12" x2="6" y2="12" />
      <line x1="10" y1="12" x2="10" y2="12" />
      <line x1="14" y1="12" x2="14" y2="15" />
      <line x1="6" y1="15" x2="6" y2="15" />
      <line x1="10" y1="15" x2="10" y2="15" />
    </svg>
  );
}

export function IconTopology({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <circle cx="10" cy="4" r="2" />
      <circle cx="4" cy="16" r="2" />
      <circle cx="16" cy="16" r="2" />
      <line x1="8.6" y1="5.4" x2="5.4" y2="14.6" />
      <line x1="11.4" y1="5.4" x2="14.6" y2="14.6" />
      <line x1="6" y1="16" x2="14" y2="16" />
    </svg>
  );
}

export function IconRoute({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <circle cx="4.5" cy="15.5" r="2" />
      <circle cx="15.5" cy="4.5" r="2" />
      <path d="M4.5 13.5V10a3 3 0 0 1 3-3h5a3 3 0 0 0 3-3" />
    </svg>
  );
}

export function IconSignpost({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <line x1="10" y1="2.5" x2="10" y2="17.5" />
      <path d="M10 5h5.5l-1.6 1.8L15.5 8.6H10" />
      <path d="M10 10.5H4.5l1.6 1.8L4.5 14h5.5" />
    </svg>
  );
}

export function IconCloud({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M5.5 15a3.3 3.3 0 0 1-.5-6.55A4.2 4.2 0 0 1 13 6.7a3.4 3.4 0 0 1 1.5 6.3" />
      <path d="M5.5 15h9a2.6 2.6 0 0 0 0-5.2h-.2A4.2 4.2 0 0 0 6 8.4" />
    </svg>
  );
}

export function IconLink({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M8 12.2 12.2 8" />
      <path d="M9.4 5.6 11 4a3 3 0 1 1 4.2 4.2l-1.6 1.6" />
      <path d="M10.6 14.4 9 16a3 3 0 1 1-4.2-4.2l1.6-1.6" />
    </svg>
  );
}

export function IconShield({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M10 2.5 16 5v5c0 4.2-2.6 6.7-6 8-3.4-1.3-6-3.8-6-8V5Z" />
    </svg>
  );
}

export function IconShieldCheck({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M10 2.5 16 5v5c0 4.2-2.6 6.7-6 8-3.4-1.3-6-3.8-6-8V5Z" />
      <path d="M7.3 9.8 9.2 11.7 12.8 8" />
    </svg>
  );
}

export function IconShieldBolt({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M10 2.5 16 5v5c0 4.2-2.6 6.7-6 8-3.4-1.3-6-3.8-6-8V5Z" />
      <path d="M10.8 7 8.3 10.6h2l-1 2.8 3-3.8h-2z" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconBolt({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M11 2.5 4.5 11h4L8 17.5 15.5 9h-4z" />
    </svg>
  );
}

export function IconPlug({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M7 2.5v4M13 2.5v4" />
      <path d="M4.5 6.5h11v3a5.5 5.5 0 0 1-11 0z" />
      <line x1="10" y1="14.5" x2="10" y2="17.5" />
    </svg>
  );
}

export function IconGitBranch({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <circle cx="5.5" cy="4.5" r="1.7" />
      <circle cx="5.5" cy="15.5" r="1.7" />
      <circle cx="14.5" cy="9.5" r="1.7" />
      <line x1="5.5" y1="6.2" x2="5.5" y2="13.8" />
      <path d="M5.5 6.2a7 7 0 0 0 7.3 3" />
    </svg>
  );
}

export function IconCheckCircle({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <circle cx="10" cy="10" r="7.2" />
      <path d="M7 10.2 9.1 12.3 13.2 7.8" />
    </svg>
  );
}

export function IconActivity({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M2.5 10.5h3l1.8-5.5 3 10 1.8-5.5h5.4" />
    </svg>
  );
}

export function IconAlertTriangle({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M10 3 17.5 16h-15Z" />
      <line x1="10" y1="8" x2="10" y2="11.5" />
      <circle cx="10" cy="13.6" r="0.15" fill="currentColor" />
    </svg>
  );
}

export function IconFileText({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M6 2.5h5.5L15 6v11.5H6Z" />
      <line x1="8" y1="9.5" x2="13" y2="9.5" />
      <line x1="8" y1="12.5" x2="13" y2="12.5" />
      <line x1="8" y1="6.5" x2="10" y2="6.5" />
    </svg>
  );
}

export function IconSparkle({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M10 2.5 11.3 7.7 16.5 9 11.3 10.3 10 15.5 8.7 10.3 3.5 9 8.7 7.7Z" />
    </svg>
  );
}

export function IconSettings({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 3.2v1.8M10 15v1.8M16.8 10h-1.8M5 10H3.2M14.9 5.1l-1.3 1.3M6.4 13.6l-1.3 1.3M14.9 14.9l-1.3-1.3M6.4 6.4 5.1 5.1" />
    </svg>
  );
}

export function IconSearch({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <circle cx="9" cy="9" r="5.5" />
      <line x1="13.2" y1="13.2" x2="17" y2="17" />
    </svg>
  );
}

export function IconBell({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M5 14.5v-4a5 5 0 0 1 10 0v4l1.3 1.8H3.7Z" />
      <path d="M8.2 17.2a1.9 1.9 0 0 0 3.6 0" />
    </svg>
  );
}

export function IconChevronDown({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M5 7.5 10 12.5 15 7.5" />
    </svg>
  );
}

export function IconLogout({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M8 3.5H5a1.5 1.5 0 0 0-1.5 1.5v10A1.5 1.5 0 0 0 5 16.5h3" />
      <path d="M12.5 6.5 16 10l-3.5 3.5" />
      <line x1="16" y1="10" x2="7.5" y2="10" />
    </svg>
  );
}

export function IconTag({ className }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={className} {...base}>
      <path d="M10.6 2.8H16a1.2 1.2 0 0 1 1.2 1.2v5.4a1.2 1.2 0 0 1-.35.85l-6.6 6.6a1.2 1.2 0 0 1-1.7 0L3.2 11.45a1.2 1.2 0 0 1 0-1.7l6.55-6.6a1.2 1.2 0 0 1 .85-.35Z" />
      <circle cx="13.2" cy="6.8" r="1" />
    </svg>
  );
}

export const NAV_ICONS: Record<string, (p: IconProps) => JSX.Element> = {
  "/dashboard": IconDashboard,
  "/network-inventory": IconServer,
  "/ipam": IconDatabase,
  "/ipam-sync": IconPlug,
  "/subnet-calculator": IconCalculator,
  "/topology": IconTopology,
  "/path-analyzer": IconRoute,
  "/routing": IconSignpost,
  "/cloud-networks": IconCloud,
  "/connectivity": IconLink,
  "/naming": IconTag,
  "/firewalls": IconShield,
  "/security-policies": IconShieldCheck,
  "/fw-automation": IconShieldBolt,
  "/automation": IconBolt,
  "/integrations": IconPlug,
  "/changes": IconGitBranch,
  "/compliance": IconCheckCircle,
  "/monitoring": IconActivity,
  "/incidents": IconAlertTriangle,
  "/reports": IconFileText,
  "/ai-assistant": IconSparkle,
  "/administration": IconSettings,
};

"use client";

import { ReactNode } from "react";

interface Props {
  children: ReactNode;
  footer?: ReactNode;
}

export function Sidebar({ children, footer }: Props) {
  return (
    <aside className="lg:sticky lg:top-4 lg:self-start lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
      <div className="pixel-border bg-white p-5 flex flex-col gap-5">
        {children}
        {footer && (
          <>
            <div className="h-[2px] bg-black" />
            {footer}
          </>
        )}
      </div>
    </aside>
  );
}

export function SidebarDivider() {
  return <div className="h-[2px] bg-[#E8E2D6]" />;
}

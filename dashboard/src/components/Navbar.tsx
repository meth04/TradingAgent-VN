"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const navItems = [
  { href: "/", label: "Trang chủ" },
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/trading-view", label: "Trading View" },
  { href: "/portfolio", label: "Danh mục" },
  { href: "/agents", label: "Workflow" },
  { href: "/blogs", label: "Báo cáo" },
  { href: "/about", label: "Giới thiệu" },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <header className="navbar w-full border-b-2 border-border bg-bg-header px-3 md:px-6 xl:px-8">
      <div className="mx-auto flex w-full max-w-[1560px] items-center justify-between gap-4 py-4">
        <div className="min-w-0 shrink-0">
          <Link href="/" className="flex items-baseline gap-2 whitespace-nowrap">
            <span className={`${vt323.className} text-[28px] tracking-[0.08em] text-black md:text-[34px]`}>
              TradingAgent-VN
            </span>
          </Link>
        </div>

        <nav className="hidden min-w-0 flex-1 flex-nowrap items-center justify-center gap-3 overflow-hidden text-[12px] font-mono tracking-[0.08em] text-black lg:flex xl:gap-5">
          {navItems.map((item, index) => {
            const active = pathname === item.href;
            return (
              <div key={item.href} className="flex min-w-0 flex-nowrap items-center gap-3 whitespace-nowrap xl:gap-5">
                <Link
                  href={item.href}
                  className={`transition-colors ${active ? "text-[#10A37F] font-bold" : "text-black hover:text-[#10A37F]"}`}
                >
                  {item.label}
                </Link>
                {index < navItems.length - 1 ? <span className="text-[#666666]">|</span> : null}
              </div>
            );
          })}
        </nav>

        <div className="hidden max-w-[250px] shrink-0 text-right text-[10px] tracking-[0.12em] text-[#666666] font-mono leading-relaxed xl:block">
          Dữ liệu nhằm mục đích diễn giải hệ thống
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-[1560px] flex-wrap items-center gap-3 border-t border-[#D0D0D0] py-3 text-[10px] font-mono tracking-[0.12em] text-black lg:hidden">
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`transition-colors ${active ? "text-[#10A37F] font-bold" : "text-black hover:text-[#10A37F]"}`}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </header>
  );
}

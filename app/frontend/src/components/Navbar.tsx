"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const navItems = [
  { href: "/", label: "Trang chủ" },
  { href: "/portfolio", label: "Danh mục" },
  { href: "/history", label: "Lịch sử" },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <header className="w-full border-b-2 border-black bg-white px-3 md:px-6 xl:px-8">
      <div className="mx-auto flex w-full max-w-[1560px] items-center justify-between gap-4 py-4">
        <Link href="/" className="flex items-baseline gap-2 whitespace-nowrap">
          <span
            className={`${vt323.className} text-[28px] tracking-[0.08em] text-black md:text-[34px]`}
          >
            StockAnalyzer-VN
          </span>
        </Link>

        <nav className="hidden min-w-0 flex-1 items-center justify-center gap-3 text-[12px] font-mono tracking-[0.08em] text-black lg:flex xl:gap-5">
          {navItems.map((item, index) => {
            const active = pathname === item.href;
            return (
              <div key={item.href} className="flex items-center gap-3 xl:gap-5">
                <Link
                  href={item.href}
                  className={`transition-colors ${
                    active
                      ? "text-[#FAAD14] font-bold"
                      : "text-black hover:text-[#FAAD14]"
                  }`}
                >
                  {item.label}
                </Link>
                {index < navItems.length - 1 ? (
                  <span className="text-[#888888]">|</span>
                ) : null}
              </div>
            );
          })}
        </nav>

        <div className="hidden items-center gap-2 text-right text-[10px] tracking-[0.18em] uppercase text-[#555555] font-mono xl:flex">
          <span className="dot" />
          <span>Multi-Agent · Real-time</span>
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-[1560px] flex-wrap items-center gap-3 border-t border-[#D0D0D0] py-3 text-[10px] font-mono tracking-[0.12em] text-black lg:hidden">
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`transition-colors ${
                active
                  ? "text-[#FAAD14] font-bold"
                  : "text-black hover:text-[#FAAD14]"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </header>
  );
}

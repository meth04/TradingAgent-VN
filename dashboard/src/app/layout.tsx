import type { Metadata } from "next";
import { Inter, JetBrains_Mono, VT323 } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { PlaybackSlider } from "@/components/PlaybackSlider";
import { PlaybackProvider } from "@/contexts/PlaybackContext";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains" });
const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

export const metadata: Metadata = {
  title: "TradingAgent-VN Dashboard",
  description: "TradingAgent-VN thesis dashboard and workflow presentation surface",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrains.variable} ${vt323.variable}`}>
      <body className="min-h-screen bg-bg-primary text-text-primary antialiased">
        <PlaybackProvider>
          <div className="min-h-screen bg-[linear-gradient(to_bottom,_#FFFFFF,_#FFFFFF)]">
            <Navbar />
            <main className="w-full pb-6">{children}</main>
            {/* TODO: Re-enable playback slider when needed */}
            {/* <PlaybackSlider /> */}
          </div>
        </PlaybackProvider>
      </body>
    </html>
  );
}

import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-primary": "#FAF7F2",
        "bg-card": "#FFFFFF",
        "bg-header": "#FFFFFF",
        "bg-warm": "#F5F1E9",
        "bg-soft": "#F9F6F1",
        "bg-tint": "#F3EFE7",
        "text-primary": "#1A1A1A",
        "text-secondary": "#555555",
        "text-header": "#000000",
        "accent-green": "#10A37F",
        "accent-red": "#EF4444",
        "accent-gold": "#FAAD14",
        "accent-coral": "#FF6B35",
        "accent-lilac": "#8B5CF6",
        border: "#000000",
        "border-light": "#D0D0D0",
      },
    },
  },
  plugins: [],
};

export default config;

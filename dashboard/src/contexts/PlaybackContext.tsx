"use client";

import { createContext, useContext, useMemo, useState, ReactNode } from "react";

export type PlaybackContextType = {
  dates: string[];
  currentDate: string | null;
  setCurrentDate: (date: string) => void;
  setDates: (dates: string[]) => void;
};

const PlaybackContext = createContext<PlaybackContextType | undefined>(undefined);

export function PlaybackProvider({ children }: { children: ReactNode }) {
  const [dates, setDates] = useState<string[]>([]);
  const [currentDate, setCurrentDate] = useState<string | null>(null);

  const value = useMemo(
    () => ({ dates, currentDate, setCurrentDate, setDates }),
    [dates, currentDate]
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}

export function usePlayback() {
  const ctx = useContext(PlaybackContext);
  if (!ctx) {
    throw new Error("usePlayback must be used within PlaybackProvider");
  }
  return ctx;
}

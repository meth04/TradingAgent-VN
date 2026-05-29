"use client";

import { useEffect } from "react";
import { usePlayback } from "@/contexts/PlaybackContext";

export function PlaybackInit({ dates }: { dates: string[] }) {
  const { dates: ctxDates, setDates, currentDate, setCurrentDate } = usePlayback();

  useEffect(() => {
    if (dates.length && ctxDates.length === 0) {
      setDates(dates);
      if (!currentDate) setCurrentDate(dates[dates.length - 1]);
    }
  }, [dates, ctxDates.length, setDates, currentDate, setCurrentDate]);

  return null;
}

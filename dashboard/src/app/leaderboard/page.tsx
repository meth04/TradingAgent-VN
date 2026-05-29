import { getPlaybackDates, loadAllLedgers, loadStates } from "@/lib/data";
import { LeaderboardClient } from "@/components/LeaderboardClient";

export default function LeaderboardPage() {
  const states = loadStates();
  const playbackDates = getPlaybackDates(states);
  const ledgersAll = loadAllLedgers();

  return <LeaderboardClient states={states} ledgersAll={ledgersAll} playbackDates={playbackDates} />;
}

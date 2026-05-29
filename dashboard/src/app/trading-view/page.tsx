import { getPlaybackDates, loadAllLedgers, loadStates } from "@/lib/data";
import { TradingViewClient } from "@/components/TradingViewClient";

export default async function TradingViewPage({ searchParams }: { searchParams: Promise<{ workflow?: string }> }) {
  const params = await searchParams;
  const states = loadStates();
  const playbackDates = getPlaybackDates(states);
  const ledgersAll = loadAllLedgers();
  return (
    <TradingViewClient
      states={states}
      playbackDates={playbackDates}
      ledgersAll={ledgersAll}
      highlightWorkflow={params.workflow}
    />
  );
}

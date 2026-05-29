import { getPlaybackDates, loadStates } from "@/lib/data";
import { PortfolioClient } from "@/components/PortfolioClient";

export default async function PortfolioPage() {
  const states = loadStates();
  const playbackDates = getPlaybackDates(states);

  return <PortfolioClient states={states} playbackDates={playbackDates} />;
}

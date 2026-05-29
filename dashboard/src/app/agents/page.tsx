import { listAnalysisDates, loadStates, getPlaybackDates } from "@/lib/data";
import { AgentsClient } from "@/components/AgentsClient";
import { PlaybackInit } from "@/components/PlaybackInit";

export default function AgentsPage() {
  const analysisDates = listAnalysisDates();
  const states = loadStates();
  const playbackDates = getPlaybackDates(states);

  return (
    <div className="w-full">
      <PlaybackInit dates={playbackDates} />
      <AgentsClient analysisDates={analysisDates} />
    </div>
  );
}

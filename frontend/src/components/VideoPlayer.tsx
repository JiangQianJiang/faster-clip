import { forwardRef } from "react";
import DraggableSubtitleOverlay from "./DraggableSubtitleOverlay";

interface Props {
  taskId: string;
  src: string;
  activeText: string;
  autoPlay?: boolean;
  onTimeUpdate?: (time: number) => void;
  onDurationChange?: (duration: number) => void;
  onPlayStateChange?: (playing: boolean) => void;
  onLoadedMetadata?: () => void;
  onEnded?: () => void;
  onError?: (error: MediaError | null) => void;
}

const VideoPlayer = forwardRef<HTMLVideoElement, Props>(function VideoPlayer(
  {
    taskId,
    src,
    activeText,
    autoPlay,
    onTimeUpdate,
    onDurationChange,
    onPlayStateChange,
    onLoadedMetadata,
    onEnded,
    onError,
  },
  ref,
) {
  return (
    <div
      style={{
        background: "#000",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        position: "relative",
        width: "100%",
        height: "100%",
      }}
    >
      <video
        ref={ref}
        src={src}
        autoPlay={autoPlay}
        controls
        onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
        onSeeked={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          onDurationChange?.(e.currentTarget.duration || 0);
          onLoadedMetadata?.();
        }}
        onPlay={() => onPlayStateChange?.(true)}
        onPause={() => onPlayStateChange?.(false)}
        onEnded={onEnded}
        onError={(e) => onError?.(e.currentTarget.error)}
        style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
      />
      <DraggableSubtitleOverlay taskId={taskId} text={activeText} />
    </div>
  );
});

export default VideoPlayer;

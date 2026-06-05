import { useRef, useState, DragEvent } from "react";
import { THEME } from "../theme";

interface Props {
  onFile: (file: File) => void;
}

export default function UploadZone({ onFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      style={{
        border: `2px dashed ${dragOver ? THEME.colors.textPrimary : THEME.colors.border}`,
        borderRadius: THEME.radius.md,
        padding: 40,
        textAlign: "center",
        cursor: "pointer",
        background: dragOver ? THEME.colors.bgHover : THEME.colors.bgPage,
        transition: "all 0.2s",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".mp4,.mov,.mkv,.avi,.webm,.m4v,.flv"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
        }}
      />
      <p style={{ margin: 0, color: THEME.colors.textSecondary }}>
        拖拽视频文件到此处或点击选择
      </p>
      <p style={{ margin: "8px 0 0", fontSize: THEME.fontSize.sm, color: THEME.colors.textMuted }}>
        支持 MP4、MOV、MKV、AVI、WebM、M4V（最大 2GB，最长 2 小时）
      </p>
    </div>
  );
}

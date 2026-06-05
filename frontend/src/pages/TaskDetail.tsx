import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useTask } from "../hooks/useTask";
import ClipCard from "../components/ClipCard";
import ClipPreviewModal from "../components/ClipPreviewModal";
import SubtitleEditorModal from "../components/SubtitleEditorModal";
import SubtitleBrowserModal, { type BrowseStatus } from "../components/SubtitleBrowserModal";
import TranscriptPanel from "../components/TranscriptPanel";
import ChatPanel from "../components/ChatPanel";
import { getTranscript } from "../api/client";
import { useToast } from "../components/Toast";
import Button from "../ui/Button";
import Badge from "../ui/Badge";
import Card from "../ui/Card";
import { THEME } from "../theme";
import type { TranscriptResponse } from "../api/client";

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中",
  extracting_subtitles: "正在提取字幕",
  analyzing: "正在分析精彩片段",
  exporting_clips: "正在导出片段",
};

const STAGES = [
  { key: "extracting_subtitles", label: "提取字幕" },
  { key: "analyzing", label: "分析片段" },
  { key: "exporting_clips", label: "导出片段" },
];

export default function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>();
  const { task, error, notFound, staleWarning, resetStale, refresh } = useTask(taskId);
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [mode, setMode] = useState<"classic" | "ai">("classic");
  const [previewClipIndex, setPreviewClipIndex] = useState<number | null>(null);
  const [editingTranscript, setEditingTranscript] = useState<TranscriptResponse | null>(null);
  const [browsingState, setBrowsingState] = useState<BrowseStatus | null>(null);
  const browseRequestRef = useRef(0);

  // Invalidate in-flight browse requests on unmount
  useEffect(() => {
    return () => { browseRequestRef.current += 1; };
  }, []);

  const closeBrowser = () => {
    browseRequestRef.current += 1;
    setBrowsingState(null);
  };

  useEffect(() => {
    if (notFound) {
      const timer = setTimeout(() => navigate("/", { replace: true }), 2000);
      return () => clearTimeout(timer);
    }
  }, [notFound, navigate]);

  if (notFound) {
    return (
      <Card style={{ maxWidth: 600, margin: "60px auto", textAlign: "center" }}>
        <p style={{ color: THEME.colors.errorText, fontSize: 16 }}>任务已被删除</p>
        <p style={{ color: THEME.colors.textMuted, fontSize: 13, marginTop: 8 }}>
          即将自动返回首页...
        </p>
        <Link to="/" style={{ color: THEME.colors.textPrimary }}>返回首页</Link>
      </Card>
    );
  }

  if (error) {
    return (
      <Card style={{ maxWidth: 600, margin: "60px auto", textAlign: "center" }}>
        <p style={{ color: THEME.colors.errorText }}>加载失败: {error}</p>
        <Link to="/" style={{ color: THEME.colors.textPrimary }}>返回首页</Link>
      </Card>
    );
  }

  if (!task) {
    return (
      <div style={{ maxWidth: 600, margin: "60px auto", textAlign: "center", color: THEME.colors.textMuted }}>
        加载中...
      </div>
    );
  }

  const isTerminal = task.status === "done" || task.status === "error";
  const canUseAi = true;
  const stageLabel = task.stage ? STAGE_LABELS[task.stage] || task.stage : task.status;

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: THEME.spacing.xl }}>
      <h2 style={{ marginTop: 0, marginBottom: THEME.spacing.sm, color: THEME.colors.textPrimary }}>
        {task.video_filename || "任务详情"}
      </h2>

      <div style={{ display: "flex", gap: THEME.spacing.lg, alignItems: "center", marginBottom: THEME.spacing.lg }}>
        <Badge
          variant={
            !isTerminal ? "info"
            : task.status === "done" ? "success"
            : "error"
          }
        >
          {stageLabel}
        </Badge>

        {!isTerminal && task.stage && (
          <div style={{ display: "flex", alignItems: "center", gap: THEME.spacing.xs }}>
            {STAGES.map((s, i) => {
              const currentIdx = STAGES.findIndex((st) => st.key === task.stage);
              const done = i < currentIdx;
              const active = i === currentIdx;
              return (
                <div key={s.key} style={{ display: "flex", alignItems: "center", gap: THEME.spacing.xs }}>
                  {i > 0 && (
                    <span style={{ color: done ? THEME.colors.successText : THEME.colors.border, fontSize: THEME.fontSize.caption }}>▸</span>
                  )}
                  <span style={{
                    fontSize: THEME.fontSize.sm,
                    color: done ? THEME.colors.successText : active ? THEME.colors.infoText : THEME.colors.textMuted,
                    fontWeight: active ? 600 : 400,
                  }}>
                    {s.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* AI mode toggle */}
        <div style={{ marginLeft: "auto", display: "flex", background: THEME.colors.bgHover, borderRadius: THEME.radius.sm, padding: 2 }}>
          <button
            onClick={() => setMode("classic")}
            style={{
              padding: "4px 12px", border: "none", borderRadius: 4,
              fontSize: THEME.fontSize.sm, cursor: "pointer",
              background: mode === "classic" ? THEME.colors.bgWhite : "transparent",
              color: mode === "classic" ? THEME.colors.textPrimary : THEME.colors.textSecondary,
              fontWeight: mode === "classic" ? 500 : 400,
              boxShadow: mode === "classic" ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
            }}
          >
            经典
          </button>
          <button
            onClick={() => setMode("ai")}
            disabled={!canUseAi}
            title={!canUseAi ? "任务完成后才能使用 AI 模式" : undefined}
            style={{
              padding: "4px 12px", border: "none", borderRadius: 4,
              fontSize: THEME.fontSize.sm, cursor: canUseAi ? "pointer" : "not-allowed",
              background: mode === "ai" ? THEME.colors.bgWhite : "transparent",
              color: canUseAi ? (mode === "ai" ? THEME.colors.textPrimary : THEME.colors.textSecondary) : THEME.colors.textMuted,
              fontWeight: mode === "ai" ? 500 : 400,
              boxShadow: mode === "ai" ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
            }}
          >
            AI
          </button>
        </div>

        {task.empty_clips_reason && (
          <span style={{ fontSize: THEME.fontSize.sm, color: THEME.colors.textSecondary }}>
            {task.empty_clips_reason}
          </span>
        )}
      </div>

      {staleWarning && !isTerminal && (
        <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 12 }}>
          <Badge variant="warning">处理时间较长，请耐心等待或返回稍后再查看</Badge>
          <Button variant="primary" size="sm" onClick={resetStale}>
            继续等待
          </Button>
        </div>
      )}

      {task.error_message && (
        <Card style={{ marginBottom: 16, background: THEME.colors.errorBg }}>
          <p style={{ margin: 0, color: THEME.colors.errorText, fontSize: 14 }}>
            {task.error_message}
          </p>
          {task.failed_stage && (
            <p style={{ margin: "4px 0 0", fontSize: 12 }}>
              <Badge variant="error">失败阶段: {STAGE_LABELS[task.failed_stage] || task.failed_stage}</Badge>
            </p>
          )}
        </Card>
      )}

      {mode === "classic" && (
        <>
          {task.clips && task.clips.length > 0 && (
            <div style={{ marginBottom: THEME.spacing.xl }}>
              <h3 style={{ marginBottom: THEME.spacing.md, color: THEME.colors.textPrimary }}>精彩片段 ({task.clips.length})</h3>
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
                gap: THEME.spacing.lg,
              }}>
                {task.clips.map((clip, i) => (
                  <ClipCard
                    key={i}
                    clip={clip}
                    index={i}
                    taskId={task.task_id}
                    onPreview={setPreviewClipIndex}
                    onDelete={async (index) => {
                      try {
                        const { authFetch } = await import("../auth");
const res = await authFetch(`/api/tasks/${task.task_id}/clips/${index}`, { method: "DELETE" });
                        if (res.ok) {
                          refresh();
                        } else {
                          const err = await res.json().catch(() => ({}));
                          showToast(err.detail || "删除失败", "error");
                        }
                      } catch {
                        showToast("删除请求失败", "error");
                      }
                    }}
                  />
                ))}
              </div>
            </div>
          )}

          {isTerminal && task.clips && task.clips.length === 0 && !task.empty_clips_reason && (
            <div style={{ textAlign: "center", padding: 40, color: THEME.colors.textMuted }}>
              未找到精彩片段
            </div>
          )}

          {task.status !== "pending" && task.status !== "queued" && taskId && (
            <div style={{ marginTop: task.clips && task.clips.length > 0 ? THEME.spacing.xl : 0 }}>
              <TranscriptPanel
                taskId={taskId}
                status={task.status}
                stage={task.stage}
                completedAt={task.completed_at}

                transcriptSource={task.transcript_source}
                onEdit={setEditingTranscript}
                onBrowse={() => {
                  const requestId = ++browseRequestRef.current;
                  setBrowsingState({ status: "loading" });
                  getTranscript(taskId).then((data) => {
                    if (browseRequestRef.current !== requestId) return;
                    if (data && data.available && data.segments.length > 0) {
                      setBrowsingState({ status: "ready", segments: data.segments });
                    } else {
                      setBrowsingState(null);
                    }
                  }).catch((err) => {
                    if (browseRequestRef.current !== requestId) return;
                    setBrowsingState({ status: "error", message: String(err) });
                  });
                }}
              />
            </div>
          )}
        </>
      )}

      {mode === "ai" && taskId && (
        <ChatPanel
          taskId={taskId}
          hasTranscript={(task.subtitle_segment_count ?? 0) > 0}
          chatHistoryJson={task.chat_history_json}
          taskStatus={task.status}
          clipsCount={task.clips?.length ?? 0}
          exportedClipsCount={task.clips?.filter((c) => c.status === "success").length ?? 0}
          onOpenEditor={() => {
            getTranscript(taskId).then((data) => {
              if (data && data.available) {
                setEditingTranscript(data);
                setMode("classic");
              } else {
                setMode("classic");
              }
            }).catch(() => {
              setMode("classic");
            });
          }}
          onPreviewClip={(index) => setPreviewClipIndex(index)}
          onTaskChanged={refresh}
        />
      )}

      {previewClipIndex !== null && task.clips[previewClipIndex] && (task.clips[previewClipIndex].status === "success" ? (
        <ClipPreviewModal
          clip={task.clips[previewClipIndex]}
          index={previewClipIndex}
          taskId={task.task_id}
          onSaved={() => { refresh(); setPreviewClipIndex(null); }}
          onClose={() => setPreviewClipIndex(null)}
        />
      ) : (
        <div
          onClick={() => setPreviewClipIndex(null)}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
            display: "flex", alignItems: "center", justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff", borderRadius: 12, padding: 32,
              boxShadow: "0 4px 24px rgba(0,0,0,0.12)", textAlign: "center",
              maxWidth: 400,
            }}
          >
            <p style={{ fontSize: 15, color: "#333", marginBottom: 8 }}>
              该片段尚未导出
            </p>
            <p style={{ fontSize: 13, color: "#999", marginBottom: 20 }}>
              请在 AI 模式中说"导出片段"来生成 MP4 视频
            </p>
            <Button variant="primary" size="sm" onClick={() => setPreviewClipIndex(null)}>
              知道了
            </Button>
          </div>
        </div>
      ))}

      {editingTranscript && (
        <SubtitleEditorModal
          task={task}
          transcript={editingTranscript}
          onClose={() => setEditingTranscript(null)}
          onSaved={() => {
            setEditingTranscript(null);
            refresh();
          }}
        />
      )}

      {browsingState && taskId && (
        <SubtitleBrowserModal
          taskId={taskId}
          browseStatus={browsingState}
          onClose={closeBrowser}
        />
      )}

    </div>
  );
}

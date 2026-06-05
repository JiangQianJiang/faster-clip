import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { TaskListItem } from "../api/client";
import { useSettingsContext } from "../context/SettingsContext";
import { THEME } from "../theme";
import Button from "../ui/Button";
import Badge from "../ui/Badge";
import ConfirmDialog from "./ConfirmDialog";

interface SidebarProps {
  tasks: TaskListItem[];
  loading: boolean;
  error: string;
  deleteError: string;
  deletingTasks: Set<string>;
  onDelete: (taskId: string) => Promise<void>;
  currentTaskId: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

function isTerminal(status: string): boolean {
  return status === "done" || status === "error";
}

export default function Sidebar({
  tasks,
  loading,
  error,
  deleteError,
  deletingTasks,
  onDelete,
  currentTaskId,
  hasMore,
  loadingMore,
  onLoadMore,
}: SidebarProps) {
  const navigate = useNavigate();
  const { settings, isConfigured, openSettings } = useSettingsContext();
  const [confirmDelete, setConfirmDelete] = useState<TaskListItem | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const handleDeleteRequest = (task: TaskListItem) => {
    setConfirmDelete(task);
  };

  const handleDeleteConfirm = () => {
    if (confirmDelete) {
      onDelete(confirmDelete.task_id);
    }
    setConfirmDelete(null);
  };

  const handleIntersection = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
        onLoadMore();
      }
    },
    [hasMore, loadingMore, loading, onLoadMore]
  );

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(handleIntersection, {
      root: el.parentElement,
      rootMargin: "100px",
      threshold: 0,
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [handleIntersection]);

  return (
    <aside
      style={{
        width: 220,
        minWidth: 220,
        height: "100vh",
        borderRight: `1px solid ${THEME.colors.border}`,
        display: "flex",
        flexDirection: "column",
        background: THEME.colors.bgPage,
      }}
    >
      <div style={{ padding: THEME.spacing.lg, borderBottom: `1px solid ${THEME.colors.borderLight}` }}>
        <div
          style={{
            fontSize: THEME.fontSize.body,
            fontWeight: 700,
            color: THEME.colors.textPrimary,
            cursor: "pointer",
          }}
          onClick={() => navigate("/")}
        >
          直播切片助手
        </div>
        <div style={{ marginTop: THEME.spacing.md }}>
          <Button variant="primary" style={{ width: "100%" }} onClick={() => navigate("/upload")}>
            + 新建任务
          </Button>
        </div>
      </div>

      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "8px 0",
        }}
      >
        <div
          style={{
            padding: `${THEME.spacing.xs}px ${THEME.spacing.md}px ${THEME.spacing.sm}px`,
            fontSize: THEME.fontSize.sm,
            color: THEME.colors.textMuted,
            fontWeight: 600,
          }}
        >
          历史任务
        </div>

        {loading && (
          <div style={{ padding: THEME.spacing.lg, fontSize: THEME.fontSize.sm, color: THEME.colors.textMuted }}>
            Loading...
          </div>
        )}

        {error && (
          <div style={{ padding: THEME.spacing.lg, fontSize: THEME.fontSize.sm, color: THEME.colors.errorText }}>
            <Badge variant="error">加载失败</Badge>
          </div>
        )}

        {deleteError && (
          <div
            style={{
              padding: THEME.spacing.sm,
              fontSize: THEME.fontSize.sm,
              color: THEME.colors.errorText,
              background: THEME.colors.errorBg,
              margin: `${THEME.spacing.xs}px ${THEME.spacing.sm}px`,
              borderRadius: THEME.radius.sm,
            }}
          >
            删除失败: {deleteError}
          </div>
        )}

        {!loading && !error && tasks.length === 0 && (
          <div style={{ padding: THEME.spacing.lg, fontSize: THEME.fontSize.sm, color: THEME.colors.textMuted }}>
            暂无历史任务
          </div>
        )}

        {tasks.map((task) => {
          const isDeleting = deletingTasks.has(task.task_id);
          const isActive = task.task_id === currentTaskId;
          const terminal = isTerminal(task.status);
          return (
            <div
              key={task.task_id}
              style={{
                display: "flex",
                alignItems: "center",
                padding: `${THEME.spacing.sm}px ${THEME.spacing.md}px`,
                cursor: "pointer",
                fontSize: THEME.fontSize.sm,
                background: isActive ? THEME.colors.border : "transparent",
              }}
              onMouseEnter={(e) => {
                if (!isActive) (e.currentTarget as HTMLElement).style.background = THEME.colors.bgHover;
              }}
              onMouseLeave={(e) => {
                if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent";
              }}
            >
              <Badge variant={terminal ? (task.status === "done" ? "success" : "error") : "info"}>&nbsp;</Badge>
              <span
                style={{
                  flex: 1,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  color: THEME.colors.textPrimary,
                  marginLeft: THEME.spacing.sm,
                }}
                onClick={() => navigate(`/tasks/${task.task_id}`)}
                title={task.video_filename || task.task_id}
              >
                {task.video_filename || task.task_id}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (!isDeleting) handleDeleteRequest(task);
                }}
                disabled={isDeleting}
                title="删除任务"
                style={{
                  marginLeft: THEME.spacing.xs,
                  padding: "2px 6px",
                  fontSize: 14,
                  lineHeight: 1,
                  background: "transparent",
                  border: "none",
                  color: THEME.colors.textMuted,
                  cursor: isDeleting ? "not-allowed" : "pointer",
                  borderRadius: THEME.radius.sm,
                  opacity: isDeleting ? 0.4 : 1,
                }}
              >
                &#x1F5D1;
              </button>
            </div>
          );
        })}

        {/* IntersectionObserver sentinel for infinite scroll */}
        <div ref={sentinelRef} style={{ height: 1 }} />
        {loadingMore && (
          <div style={{ padding: THEME.spacing.sm, fontSize: THEME.fontSize.sm, color: THEME.colors.textMuted, textAlign: "center" }}>
            加载中...
          </div>
        )}
        {!hasMore && tasks.length > 0 && (
          <div style={{ padding: THEME.spacing.sm, fontSize: THEME.fontSize.caption, color: THEME.colors.textMuted, textAlign: "center" }}>
            已加载全部
          </div>
        )}
      </div>

      <div
        style={{
          borderTop: `1px solid ${THEME.colors.borderLight}`,
          padding: THEME.spacing.sm,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: THEME.spacing.sm,
          fontSize: THEME.fontSize.sm,
          color: THEME.colors.textSecondary,
        }}
        onClick={openSettings}
        title={isConfigured ? settings.llmModel : "配置模型"}
      >
        <span>{isConfigured ? "⚙️" : "⚠️"}</span>
        <span
          style={{
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {isConfigured ? settings.llmModel : "配置模型"}
        </span>
      </div>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="删除任务"
        message={
          confirmDelete
            ? `确定要删除 ${confirmDelete.video_filename || confirmDelete.task_id} 吗？将同时删除视频文件、输出目录和所有数据，此操作不可撤销。${
                !isTerminal(confirmDelete.status)
                  ? "\n\n该任务正在处理中，删除后将中止处理并清除所有数据。"
                  : ""
              }`
            : ""
        }
        confirmLabel="删除"
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={() => setConfirmDelete(null)}
      />
    </aside>
  );
}

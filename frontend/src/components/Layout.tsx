import { useState, useEffect, useRef, useCallback } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import SettingsModal from "./SettingsModal";
import { useSettingsContext } from "../context/SettingsContext";
import { listTasks, deleteTask, TaskListItem } from "../api/client";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 10_000;

export default function Layout() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [deletingTasks, setDeletingTasks] = useState<Set<string>>(new Set());
  const location = useLocation();
  const navigate = useNavigate();
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runningRef = useRef(true);
  const { settings, saveSettings, isModalOpen, closeSettings } =
    useSettingsContext();

  const fetchTasks = useCallback(async (): Promise<boolean> => {
    try {
      const list = await listTasks(PAGE_SIZE);
      if (!runningRef.current) return false;
      setTasks(list);
      setHasMore(list.length >= PAGE_SIZE);
      setError("");
      return list.some((t) => !["done", "error"].includes(t.status));
    } catch (e) {
      if (!runningRef.current) return false;
      setError(String(e));
      return true;
    }
  }, []);

  const loadMoreTasks = useCallback(async () => {
    if (loadingMore || !hasMore || tasks.length === 0) return;
    setLoadingMore(true);
    try {
      const oldest = tasks[tasks.length - 1];
      const more = await listTasks(PAGE_SIZE, oldest.created_at);
      if (!runningRef.current) return;
      setTasks((prev) => [...prev, ...more]);
      setHasMore(more.length >= PAGE_SIZE);
    } catch (e) {
      setError(String(e));
    } finally {
      if (runningRef.current) setLoadingMore(false);
    }
  }, [loadingMore, hasMore, tasks]);
  const stopPolling = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);
  const pollTasks = useCallback(async (): Promise<boolean> => {
    try {
      const fresh = await listTasks(PAGE_SIZE);
      if (!runningRef.current) return false;
      setTasks((prev) => {
        const existingIds = new Set(prev.map((t) => t.task_id));
        const toPrepend = fresh.filter((t) => !existingIds.has(t.task_id));
        if (toPrepend.length === 0) {
          const statusMap = new Map(fresh.map((t) => [t.task_id, t]));
          let changed = false;
          const updated = prev.map((t) => {
            const f = statusMap.get(t.task_id);
            if (f && f.status !== t.status) {
              changed = true;
              return f;
            }
            return t;
          });
          return changed ? updated : prev;
        }
        return [...toPrepend, ...prev];
      });
      const active = fresh.some((t) => !["done", "error"].includes(t.status));
      const anyActive = active || tasks.some((t) => !["done", "error"].includes(t.status));
      return anyActive;
    } catch {
      return true;
    }
  }, [tasks]);
  const pollTasksRef = useRef(pollTasks);
  pollTasksRef.current = pollTasks;
  const schedulePoll = useCallback(
    (hasActive: boolean) => {
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      if (!runningRef.current || !hasActive) return;
      timeoutRef.current = setTimeout(async () => {
        timeoutRef.current = null;
        const stillActive = await pollTasksRef.current();
        schedulePollRef.current(stillActive);
      }, POLL_INTERVAL_MS);
    },
    []
  );
  const schedulePollRef = useRef(schedulePoll);
  schedulePollRef.current = schedulePoll;

  useEffect(() => {
    runningRef.current = true;
    fetchTasks().then((hasActive) => {
      if (!runningRef.current) return;
      setLoading(false);
      if (hasActive) schedulePollRef.current(hasActive);
    });
    return () => {
      runningRef.current = false;
      stopPolling();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (loading) return;
    fetchTasks().then((hasActive) => {
      if (!runningRef.current) return;
      if (hasActive) schedulePollRef.current(hasActive);
    });
  }, [location.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = async (taskId: string) => {
    setDeleteError("");
    setDeletingTasks((prev) => new Set(prev).add(taskId));
    try {
      await deleteTask(taskId);
      if (location.pathname === `/tasks/${taskId}`) {
        navigate("/", { replace: true });
      }
      if (!runningRef.current) return;
      setTasks((prev) => prev.filter((t) => t.task_id !== taskId));
    } catch (e) {
      setDeleteError(String(e));
    } finally {
      setDeletingTasks((prev) => {
        const next = new Set(prev);
        next.delete(taskId);
        return next;
      });
    }
  };

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <Sidebar
        tasks={tasks}
        loading={loading}
        error={error}
        deleteError={deleteError}
        deletingTasks={deletingTasks}
        onDelete={handleDelete}
        currentTaskId={location.pathname.startsWith("/tasks/") ? location.pathname.split("/tasks/")[1]?.split("/")[0] : null}
        hasMore={hasMore}
        loadingMore={loadingMore}
        onLoadMore={loadMoreTasks}
      />
      <main style={{ flex: 1, overflow: "auto" }}>
        <Outlet />
      </main>
      {isModalOpen && (
        <SettingsModal
          settings={settings}
          onSave={(s) => {
            saveSettings(s);
            closeSettings();
          }}
          onClose={closeSettings}
        />
      )}
    </div>
  );
}

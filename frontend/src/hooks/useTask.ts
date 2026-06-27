import { useState, useEffect, useCallback, useRef } from "react";
import { getTask, getTaskStatus, TaskResponse } from "../api/client";

export function useTask(taskId: string | undefined) {
  const [task, setTask] = useState<TaskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [staleWarning, setStaleWarning] = useState(false);
  const [pollEpoch, setPollEpoch] = useState(0);
  const delayRef = useRef(2000);
  const lastStageRef = useRef<string>("");
  const stageSinceRef = useRef(Date.now());
  // Track the active taskId to cancel stale requests
  const activeTaskIdRef = useRef<string | undefined>(undefined);
  const previousTaskIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!taskId) return;

    const taskIdChanged = previousTaskIdRef.current !== taskId;
    previousTaskIdRef.current = taskId;
    // Reset state immediately when switching tasks. Same-task refreshes keep
    // the current data mounted so child UI state, including chat turns, survives.
    if (taskIdChanged) {
      setTask(null);
      setError(null);
      setNotFound(false);
      setStaleWarning(false);
    }
    delayRef.current = 2000;
    lastStageRef.current = "";
    stageSinceRef.current = Date.now();
    activeTaskIdRef.current = taskId;

    let timer: ReturnType<typeof setTimeout>;
    const currentTaskId = taskId;

    // Full fetch: loads config, clips, media_info, etc.
    const fetchFull = async () => {
      try {
        const t = await getTask(currentTaskId);
        // Discard if task has changed since request was sent
        if (activeTaskIdRef.current !== currentTaskId) return;
        setTask(t);
        lastStageRef.current = t.stage || "";
        stageSinceRef.current = Date.now();
        setStaleWarning(false);
      } catch (e) {
        if (activeTaskIdRef.current !== currentTaskId) return;
        const msg = String(e);
        if (msg.includes("(404)")) {
          setNotFound(true);
          setError(null);
        } else {
          setError(msg);
        }
      }
    };

    // Lightweight poll: only status/stage — no ffprobe, no JSON parsing
    const poll = async (): Promise<boolean> => {
      try {
        const status = await getTaskStatus(currentTaskId);
        if (activeTaskIdRef.current !== currentTaskId) return false;

        setTask(prev => {
          if (!prev) return null;
          return {
            ...prev,
            status: status.status,
            stage: status.stage,
            error_message: status.error_message,
            failed_stage: status.failed_stage,
            empty_clips_reason: status.empty_clips_reason,
            subtitle_segment_count: status.subtitle_segment_count,
            updated_at: status.updated_at,
          };
        });

        if (status.stage && status.stage === lastStageRef.current) {
          if (Date.now() - stageSinceRef.current > 30 * 60 * 1000) {
            setStaleWarning(true);
          }
        } else {
          lastStageRef.current = status.stage || "";
          stageSinceRef.current = Date.now();
          setStaleWarning(false);
        }

        if (status.status === "done" || status.status === "error") {
          // Fetch full data once on completion to get clips/config/media_info
          fetchFull();
          return false;
        }

        delayRef.current = Math.min(delayRef.current * 1.5, 10000);
        return true;
      } catch (e) {
        if (activeTaskIdRef.current !== currentTaskId) return false;
        const msg = String(e);
        if (msg.includes("(404)")) {
          setNotFound(true);
          setError(null);
          return false;
        }
        setError(msg);
        return true;
      }
    };

    const schedule = () => {
      if (activeTaskIdRef.current !== currentTaskId) return;
      timer = setTimeout(async () => {
        const shouldContinue = await poll();
        if (activeTaskIdRef.current === currentTaskId && shouldContinue) schedule();
      }, delayRef.current);
    };

    // Initial load: full endpoint (config, clips, media_info, etc.)
    // Then switch to lightweight status polling while processing
    fetchFull().then(() => {
      if (activeTaskIdRef.current !== currentTaskId) return;
      poll().then((shouldContinue) => {
        if (activeTaskIdRef.current === currentTaskId && shouldContinue) schedule();
      });
    });

    return () => {
      // Mark as stale so in-flight requests are discarded
      activeTaskIdRef.current = undefined;
      clearTimeout(timer);
    };
  }, [taskId, pollEpoch]);

  const resetStale = useCallback(() => {
    lastStageRef.current = "";
    stageSinceRef.current = Date.now();
    setStaleWarning(false);
  }, []);

  const refresh = useCallback(() => {
    setPollEpoch((e) => e + 1);
  }, []);

  return { task, error, notFound, staleWarning, resetStale, refresh };
}

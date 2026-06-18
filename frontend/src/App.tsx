import { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { SettingsProvider } from "./context/SettingsContext";
import { ToastProvider } from "./components/Toast";
import ErrorBoundary from "./components/ErrorBoundary";
import Layout from "./components/Layout";
import LoadingSpinner from "./components/LoadingSpinner";

const Home = lazy(() => import("./pages/Home"));
const TaskDetail = lazy(() => import("./pages/TaskDetail"));
const Upload = lazy(() => import("./pages/Upload"));
function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <SettingsProvider>
          <Suspense fallback={<LoadingSpinner />}>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/" element={<Home />} />
                <Route path="/tasks/:taskId" element={<TaskDetail />} />
                <Route path="/upload" element={<Upload />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </Suspense>
        </SettingsProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}

export default App;

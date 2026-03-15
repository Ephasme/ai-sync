import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/app-shell";
import { ConfigurationPage } from "@/pages/Configuration";
import { DashboardPage } from "@/pages/Dashboard";
import { PlanApplyPage } from "@/pages/PlanApply";
import { SourceExplorerPage } from "@/pages/SourceExplorer";

const appRoutes = [
  { path: "/dashboard", element: <DashboardPage /> },
  { path: "/sources", element: <SourceExplorerPage /> },
  { path: "/configuration", element: <ConfigurationPage /> },
  { path: "/plan", element: <PlanApplyPage /> },
];

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate replace to="/dashboard" />} />
        {appRoutes.map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
        <Route path="*" element={<Navigate replace to="/dashboard" />} />
      </Route>
    </Routes>
  );
}

export default App;

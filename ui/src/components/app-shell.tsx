import {
  FileDiffIcon,
  FolderTreeIcon,
  LayoutDashboardIcon,
  Settings2Icon,
} from "lucide-react";
import { Outlet, NavLink } from "react-router-dom";

import { useStatusQuery } from "@/hooks/use-api";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";

const navigationItems = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboardIcon },
  { to: "/sources", label: "Sources", icon: FolderTreeIcon },
  { to: "/configuration", label: "Configuration", icon: Settings2Icon },
  { to: "/plan", label: "Plan & Apply", icon: FileDiffIcon },
];

function getWorkspaceName(path: string | null | undefined): string {
  if (!path) {
    return "Project workspace";
  }

  const normalizedPath = path.replace(/[\\/]+$/, "");
  const pathSegments = normalizedPath.split(/[\\/]/).filter(Boolean);
  if (pathSegments.length >= 1) {
    return pathSegments[pathSegments.length - 1];
  }

  return "Project workspace";
}

export function AppShell() {
  const statusQuery = useStatusQuery();
  const workspaceName = getWorkspaceName(
    statusQuery.data?.project_root ?? statusQuery.data?.workspace_root,
  );

  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="border-b border-sidebar-border">
          <div className="px-2 py-3">
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-sidebar-foreground/70">
              ai-sync
            </p>
            <h1 className="mt-1 text-lg font-semibold">Configuration UI</h1>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Workspace</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {navigationItems.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild tooltip={item.label}>
                      <NavLink to={item.to}>
                        <item.icon />
                        <span>{item.label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="border-t border-sidebar-border">
          <div className="px-2 py-3 text-xs text-sidebar-foreground/70">
            Inspect sources, edit selections, then plan and apply safely.
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur">
          <SidebarTrigger />
          <div>
            <p className="text-base font-semibold leading-none tracking-tight">
              {workspaceName}
            </p>
            <p className="text-xs text-muted-foreground">
              Local web interface for ai-sync
            </p>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl px-6 py-8">
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

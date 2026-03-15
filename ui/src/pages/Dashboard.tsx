import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { ProjectSetupState } from "@/components/project-setup-state";
import { QueryErrorState } from "@/components/query-state";
import { useStatusQuery } from "@/hooks/use-api";

const selectionLabels: Array<{ key: string; label: string }> = [
  { key: "agents", label: "Agents" },
  { key: "skills", label: "Skills" },
  { key: "commands", label: "Commands" },
  { key: "rules", label: "Rules" },
  { key: "mcp-servers", label: "MCP servers" },
];

export function DashboardPage() {
  const statusQuery = useStatusQuery();

  if (statusQuery.isLoading) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Dashboard"
          description="Overview of the current ai-sync project setup."
        />
        <p className="text-sm text-muted-foreground">
          Loading current setup...
        </p>
      </section>
    );
  }

  if (statusQuery.isError) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Dashboard"
          description="Overview of the current ai-sync project setup."
        />
        <QueryErrorState message={statusQuery.error.message} />
      </section>
    );
  }

  const status = statusQuery.data;
  if (!status) {
    return null;
  }

  if (!status.initialized) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Dashboard"
          description="Overview of the current ai-sync project setup."
        />
        <ProjectSetupState workspaceRoot={status.workspace_root} />
      </section>
    );
  }

  const { manifest, manifest_path, selections, sources } = status;
  const totalSelected = Object.values(selections).reduce(
    (total, items) => total + items.length,
    0,
  );

  return (
    <section className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Inspect the active manifest, resolved sources, and selected artifacts at a glance."
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="h-full">
          <CardHeader className="content-start">
            <CardTitle>Manifest</CardTitle>
            <CardDescription className="min-h-10">
              Source of truth for this project.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex min-h-20 flex-1 flex-col justify-between gap-2">
            <p className="break-all text-sm font-medium">{manifest_path}</p>
            <Badge variant="outline" className="w-fit">
              {sources.length} sources
            </Badge>
          </CardContent>
        </Card>
        <Card className="h-full">
          <CardHeader className="content-start">
            <CardTitle>Selections</CardTitle>
            <CardDescription className="min-h-10">
              Artifacts currently enabled in the manifest.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex min-h-20 flex-1 flex-col justify-between gap-2">
            <p className="text-3xl leading-none font-semibold">
              {totalSelected}
            </p>
            <p className="text-sm text-muted-foreground">
              Total selected artifacts
            </p>
          </CardContent>
        </Card>
        <Card className="h-full">
          <CardHeader className="content-start">
            <CardTitle>Mode</CardTitle>
            <CardDescription className="min-h-10">
              Current manifest settings snapshot.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex min-h-20 flex-1 flex-col justify-between gap-2">
            <Badge>{String(manifest.settings.mode ?? "normal")}</Badge>
            <p className="text-sm text-muted-foreground">
              {manifest.settings.subagents === true
                ? "Subagents enabled"
                : "Subagents disabled"}
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.1fr_1.9fr]">
        <Card>
          <CardHeader>
            <CardTitle>Selected by section</CardTitle>
            <CardDescription>
              Counts pulled from the active manifest.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {selectionLabels.map((section) => (
              <div
                key={section.key}
                className="flex items-center justify-between text-sm"
              >
                <span className="text-muted-foreground">{section.label}</span>
                <Badge variant="secondary">
                  {selections[section.key]?.length ?? 0}
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Resolved sources</CardTitle>
            <CardDescription>
              Actual source roots and their current fingerprints.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {sources.map((source) => {
              const selectedCount = Object.values(selections).reduce(
                (total, items) => {
                  return (
                    total +
                    items.filter((item) => item.startsWith(`${source.alias}/`))
                      .length
                  );
                },
                0,
              );
              return (
                <div
                  key={source.alias}
                  className="rounded-lg border border-border/70 bg-muted/30 p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium">{source.alias}</h3>
                        <Badge variant="outline">{source.kind}</Badge>
                        <Badge variant="secondary">
                          {selectedCount} selected
                        </Badge>
                      </div>
                      <p className="break-all text-sm text-muted-foreground">
                        {source.source}
                      </p>
                      {source.kind === "remote" ? (
                        <p className="break-all text-xs text-muted-foreground">
                          Cache: {source.root}
                        </p>
                      ) : null}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Fingerprint: {source.fingerprint}
                    </p>
                  </div>
                  {source.portability_warning ? (
                    <p className="mt-3 text-xs text-amber-600 dark:text-amber-400">
                      {source.portability_warning}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

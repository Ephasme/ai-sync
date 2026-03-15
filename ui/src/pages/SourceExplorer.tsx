import { useQueries } from "@tanstack/react-query";
import { ChevronDownIcon } from "lucide-react";

import { apiClient } from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { ProjectSetupState } from "@/components/project-setup-state";
import { QueryErrorState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { queryKeys, useStatusQuery } from "@/hooks/use-api";

const kindLabels: Record<string, string> = {
  agent: "Agents",
  skill: "Skills",
  command: "Commands",
  rule: "Rules",
  "mcp-server": "MCP servers",
};

export function SourceExplorerPage() {
  const statusQuery = useStatusQuery();

  const catalogQueries = useQueries({
    queries:
      statusQuery.data?.sources.map((source) => ({
        queryKey: queryKeys.sourceCatalog(source.alias),
        queryFn: () => apiClient.getSourceCatalog(source.alias),
      })) ?? [],
  });

  if (statusQuery.isLoading) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Source Explorer"
          description="Browse every artifact made available by each configured source."
        />
        <p className="text-sm text-muted-foreground">Loading sources...</p>
      </section>
    );
  }

  if (statusQuery.isError) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Source Explorer"
          description="Browse every artifact made available by each configured source."
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
          title="Source Explorer"
          description="Browse every artifact made available by each configured source."
        />
        <ProjectSetupState workspaceRoot={status.workspace_root} />
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <PageHeader
        title="Source Explorer"
        description="Inspect all discovered artifacts grouped by source and kind before enabling them."
      />

      <div className="grid gap-4">
        {status.sources.map((source, index) => {
          const catalogQuery = catalogQueries[index];
          const entries = catalogQuery.data?.entries ?? [];
          const kinds = Array.from(new Set(entries.map((entry) => entry.kind)));
          const defaultKind = kinds[0] ?? "agent";

          return (
            <Collapsible key={source.alias} defaultOpen>
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <CardTitle>{source.alias}</CardTitle>
                        <Badge variant="outline">{source.kind}</Badge>
                        <Badge variant="secondary">
                          {entries.length} artifacts
                        </Badge>
                      </div>
                      <CardDescription className="break-all">
                        {source.source}
                      </CardDescription>
                      {source.kind === "remote" ? (
                        <p className="break-all text-xs text-muted-foreground">
                          Cache: {source.root}
                        </p>
                      ) : null}
                    </div>
                    <CollapsibleTrigger asChild>
                      <Button variant="outline" size="sm">
                        Toggle
                        <ChevronDownIcon className="size-4" />
                      </Button>
                    </CollapsibleTrigger>
                  </div>
                </CardHeader>
                <CollapsibleContent>
                  <CardContent className="space-y-4">
                    {catalogQuery.isLoading ? (
                      <p className="text-sm text-muted-foreground">
                        Loading catalog...
                      </p>
                    ) : catalogQuery.isError ? (
                      <QueryErrorState message={catalogQuery.error.message} />
                    ) : (
                      <Tabs defaultValue={defaultKind} className="space-y-4">
                        <TabsList className="flex h-auto flex-wrap justify-start">
                          {kinds.map((kind) => (
                            <TabsTrigger key={kind} value={kind}>
                              {kindLabels[kind] ?? kind}
                            </TabsTrigger>
                          ))}
                        </TabsList>
                        {kinds.map((kind) => (
                          <TabsContent
                            key={kind}
                            value={kind}
                            className="space-y-3"
                          >
                            {entries
                              .filter((entry) => entry.kind === kind)
                              .map((entry) => (
                                <div
                                  key={entry.scoped_ref}
                                  className="rounded-lg border border-border/70 bg-muted/25 p-4"
                                >
                                  <div className="flex flex-wrap items-center gap-2">
                                    <p className="font-medium">{entry.name}</p>
                                    <Badge
                                      variant={
                                        entry.selected ? "default" : "outline"
                                      }
                                    >
                                      {entry.selected
                                        ? "Selected"
                                        : "Available"}
                                    </Badge>
                                  </div>
                                  <p className="mt-2 text-sm text-muted-foreground">
                                    {entry.description ||
                                      "No description available."}
                                  </p>
                                  <p className="mt-2 text-xs text-muted-foreground">
                                    {entry.scoped_ref}
                                  </p>
                                </div>
                              ))}
                          </TabsContent>
                        ))}
                      </Tabs>
                    )}
                  </CardContent>
                </CollapsibleContent>
              </Card>
            </Collapsible>
          );
        })}
      </div>
    </section>
  );
}

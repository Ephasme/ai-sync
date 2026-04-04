import { useMemo, useState } from "react";

import { useQueries } from "@tanstack/react-query";

import {
  apiClient,
  type ManifestSection,
  type ManifestSelectionChange,
} from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { QueryErrorState } from "@/components/query-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  queryKeys,
  useManifestQuery,
  usePatchManifestMutation,
  useStatusQuery,
} from "@/hooks/use-api";
import {
  applyManifestChanges,
  renderManifestPreview,
} from "@/lib/manifest-preview";
import { ProjectSetupState } from "@/components/project-setup-state";

const kindToSection: Record<string, ManifestSection> = {
  agent: "agents",
  skill: "skills",
  command: "commands",
  rule: "rules",
  "mcp-server": "mcp_servers",
};

const kindLabels: Record<string, string> = {
  agent: "Agents",
  skill: "Skills",
  command: "Commands",
  rule: "Rules",
  "mcp-server": "MCP servers",
};

export function ConfigurationPage() {
  const statusQuery = useStatusQuery();
  const manifestQuery = useManifestQuery(
    statusQuery.data?.initialized === true,
  );
  const patchManifestMutation = usePatchManifestMutation();
  const [stagedChanges, setStagedChanges] = useState<
    Record<string, ManifestSelectionChange>
  >({});

  const catalogQueries = useQueries({
    queries:
      statusQuery.data?.sources.map((source) => ({
        queryKey: queryKeys.sourceCatalog(source.alias),
        queryFn: () => apiClient.getSourceCatalog(source.alias),
      })) ?? [],
  });

  const stagedValues = Object.values(stagedChanges);
  const previewManifest = useMemo(() => {
    if (!manifestQuery.data) {
      return "";
    }
    return renderManifestPreview(
      applyManifestChanges(manifestQuery.data.manifest, stagedValues),
    );
  }, [manifestQuery.data, stagedValues]);

  if (statusQuery.isLoading || manifestQuery.isLoading) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Configuration"
          description="Enable or disable artifacts and preview the manifest changes before saving."
        />
        <p className="text-sm text-muted-foreground">
          Loading manifest and source catalogs...
        </p>
      </section>
    );
  }

  if (statusQuery.isError) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Configuration"
          description="Enable or disable artifacts and preview the manifest changes before saving."
        />
        <QueryErrorState message={statusQuery.error.message} />
      </section>
    );
  }

  if (statusQuery.data && !statusQuery.data.initialized) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Configuration"
          description="Enable or disable artifacts and preview the manifest changes before saving."
        />
        <ProjectSetupState workspaceRoot={statusQuery.data.workspace_root} />
      </section>
    );
  }

  if (manifestQuery.isError) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Configuration"
          description="Enable or disable artifacts and preview the manifest changes before saving."
        />
        <QueryErrorState message={manifestQuery.error.message} />
      </section>
    );
  }

  const status = statusQuery.data;
  const manifestData = manifestQuery.data;
  if (!status || !manifestData) {
    return null;
  }

  const handleToggle = (
    section: ManifestSection,
    scopedRef: string,
    originalEnabled: boolean,
    nextEnabled: boolean,
  ) => {
    const key = `${section}:${scopedRef}`;
    setStagedChanges((current) => {
      const next = { ...current };
      if (nextEnabled === originalEnabled) {
        delete next[key];
      } else {
        next[key] = { section, scoped_ref: scopedRef, enabled: nextEnabled };
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (stagedValues.length === 0) {
      return;
    }
    await patchManifestMutation.mutateAsync(stagedValues);
    setStagedChanges({});
  };

  return (
    <section className="space-y-6">
      <PageHeader
        title="Configuration"
        description="Stage artifact selections locally, inspect the resulting manifest preview, then persist the changes in one save."
        actions={
          <>
            <Button
              variant="outline"
              disabled={
                stagedValues.length === 0 || patchManifestMutation.isPending
              }
              onClick={() => setStagedChanges({})}
            >
              Reset
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  disabled={
                    stagedValues.length === 0 || patchManifestMutation.isPending
                  }
                >
                  Save changes
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Apply manifest changes?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will update the selected manifest file and clear the
                    cached plan.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={() => void handleSave()}>
                    Save manifest
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </>
        }
      />

      {stagedValues.length > 0 ? (
        <Alert>
          <AlertTitle>{stagedValues.length} staged change(s)</AlertTitle>
          <AlertDescription>
            Review the generated manifest preview before saving.
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <div className="space-y-4">
          {status.sources.map((source, index) => {
            const catalogQuery = catalogQueries[index];
            const entries = catalogQuery.data?.entries ?? [];
            const kinds = Array.from(
              new Set(entries.map((entry) => entry.kind)),
            );
            const defaultKind = kinds[0] ?? "agent";

            return (
              <Card key={source.alias}>
                <CardHeader>
                  <CardTitle>{source.alias}</CardTitle>
                  <CardDescription className="break-all">
                    {source.source}
                  </CardDescription>
                </CardHeader>
                <CardContent>
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
                            .map((entry) => {
                              const section = kindToSection[entry.kind];
                              const staged =
                                stagedChanges[`${section}:${entry.scoped_ref}`];
                              const checked = staged
                                ? staged.enabled
                                : entry.selected;
                              return (
                                <label
                                  key={entry.scoped_ref}
                                  className="flex items-start gap-3 rounded-lg border border-border/70 p-4"
                                >
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={(value) =>
                                      handleToggle(
                                        section,
                                        entry.scoped_ref,
                                        entry.selected,
                                        value === true,
                                      )
                                    }
                                  />
                                  <div className="min-w-0 flex-1 space-y-2">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <p className="font-medium">
                                        {entry.name}
                                      </p>
                                      <Badge
                                        variant={
                                          checked ? "default" : "outline"
                                        }
                                      >
                                        {checked ? "Enabled" : "Disabled"}
                                      </Badge>
                                      {staged ? (
                                        <Badge variant="secondary">
                                          Staged
                                        </Badge>
                                      ) : null}
                                    </div>
                                    <p className="text-sm text-muted-foreground">
                                      {entry.description ||
                                        "No description available."}
                                    </p>
                                    <p className="text-xs text-muted-foreground">
                                      {entry.scoped_ref}
                                    </p>
                                  </div>
                                </label>
                              );
                            })}
                        </TabsContent>
                      ))}
                    </Tabs>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>

        <Card className="sticky top-6">
          <CardHeader>
            <CardTitle>Manifest preview</CardTitle>
            <CardDescription>
              Projected YAML after staged changes are saved.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {stagedValues.map((change) => (
                <Badge
                  key={`${change.section}:${change.scoped_ref}`}
                  variant="outline"
                >
                  {change.enabled ? "+" : "-"} {change.scoped_ref}
                </Badge>
              ))}
            </div>
            <Separator />
            <pre className="max-h-[32rem] overflow-auto rounded-lg bg-muted/40 p-4 text-xs leading-6">
              {previewManifest || manifestData.raw}
            </pre>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

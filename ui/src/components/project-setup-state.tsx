import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBootstrapManifestMutation } from "@/hooks/use-api";

function manifestPath(root: string, filename: string) {
  return root.endsWith("/") ? `${root}${filename}` : `${root}/${filename}`;
}

export function ProjectSetupState({
  workspaceRoot,
}: {
  workspaceRoot: string;
}) {
  const bootstrapManifestMutation = useBootstrapManifestMutation();

  return (
    <Card>
      <CardHeader>
        <CardTitle>No ai-sync manifest found</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm text-muted-foreground">
        <p>
          The UI started successfully, but this folder is not initialized for
          `ai-sync` yet.
        </p>
        <div className="space-y-1">
          <p className="font-medium text-foreground">Current workspace</p>
          <p className="break-all">{workspaceRoot}</p>
        </div>
        <div className="space-y-1">
          <p className="font-medium text-foreground">
            Create one of these files
          </p>
          <p className="break-all font-mono text-xs">
            {manifestPath(workspaceRoot, ".ai-sync.yaml")}
          </p>
          <p className="break-all font-mono text-xs">
            {manifestPath(workspaceRoot, ".ai-sync.local.yaml")}
          </p>
        </div>
        <div className="space-y-2">
          <p>
            You can also generate a starter manifest now with the default
            Sherpas source:
          </p>
          <p className="break-all font-mono text-xs">
            git@github.com:Les-Sherpas/ai-sync-config-dev.git @ v1.5.0
          </p>
          <Button
            onClick={() => void bootstrapManifestMutation.mutateAsync()}
            disabled={bootstrapManifestMutation.isPending}
          >
            {bootstrapManifestMutation.isPending
              ? "Creating manifest..."
              : "Create starter manifest"}
          </Button>
        </div>
        <p>
          Once the manifest exists, the dashboard, sources, configuration, and
          plan screens will become available.
        </p>
      </CardContent>
    </Card>
  );
}

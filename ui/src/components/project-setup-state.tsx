import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function manifestPath(root: string, filename: string) {
  return root.endsWith("/") ? `${root}${filename}` : `${root}/${filename}`;
}

export function ProjectSetupState({
  workspaceRoot,
}: {
  workspaceRoot: string;
}) {
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
        <p>
          Once the manifest exists, the dashboard, sources, configuration, and
          plan screens will become available.
        </p>
      </CardContent>
    </Card>
  );
}

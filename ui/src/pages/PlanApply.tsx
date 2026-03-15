import { AlertTriangleIcon, RefreshCwIcon } from "lucide-react";

import type { PlanActionData } from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { ProjectSetupState } from "@/components/project-setup-state";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useApplyPlanMutation,
  usePlanQuery,
  useStatusQuery,
} from "@/hooks/use-api";

const clientOrder = ["cursor", "claude", "codex", "gemini", "global"] as const;
const actionColumnWidth = "8rem";
const clientColumnWidth = "8rem";

function PlanLoadingState() {
  return (
    <div className="space-y-4">
      <Alert>
        <RefreshCwIcon className="size-4 animate-spin" />
        <AlertTitle className="flex items-center gap-2">
          Preparing plan
          <Badge variant="outline">Planning</Badge>
        </AlertTitle>
        <AlertDescription>
          Reading the manifest, resolving sources, and computing the latest
          filesystem actions.
        </AlertDescription>
      </Alert>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="h-full">
          <CardHeader className="min-h-24">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-4 w-40" />
          </CardHeader>
          <CardContent className="mt-auto flex items-end">
            <Skeleton className="h-9 w-14" />
          </CardContent>
        </Card>
        <Card className="h-full">
          <CardHeader className="min-h-24">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-4 w-36" />
          </CardHeader>
          <CardContent className="mt-auto flex items-end">
            <Skeleton className="h-9 w-14" />
          </CardContent>
        </Card>
        <Card className="h-full">
          <CardHeader className="min-h-24">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-4 w-44" />
          </CardHeader>
          <CardContent className="mt-auto flex items-end">
            <Skeleton className="h-9 w-14" />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-72" />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border border-border/70">
            <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-3">
              <Skeleton className="h-5 w-16" />
              <Skeleton className="h-5 w-48" />
            </div>
            <div className="space-y-3 px-4 py-4">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          </div>
          <div className="rounded-lg border border-border/70">
            <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-3">
              <Skeleton className="h-5 w-16" />
              <Skeleton className="h-5 w-40" />
            </div>
            <div className="space-y-3 px-4 py-4">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function actionVariant(
  action: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (action === "create") {
    return "default";
  }
  if (action === "update") {
    return "secondary";
  }
  if (action === "delete") {
    return "destructive";
  }
  return "outline";
}

function groupActionsByArtifact(actions: PlanActionData[]) {
  const fallbackOrder = clientOrder.length;
  const groups = new Map<
    string,
    {
      kind: string;
      resource: string;
      name: string;
      description: string;
      actions: PlanActionData[];
    }
  >();

  for (const action of actions) {
    const key = `${action.kind}::${action.resource}`;
    const existing = groups.get(key);
    if (existing) {
      existing.actions.push(action);
      continue;
    }
    groups.set(key, {
      kind: action.kind,
      resource: action.resource,
      name: action.name,
      description: action.description,
      actions: [action],
    });
  }

  return Array.from(groups.values()).map((group) => ({
    ...group,
    actions: [...group.actions].sort((left, right) => {
      const leftIndex = clientOrder.indexOf(
        left.client as (typeof clientOrder)[number],
      );
      const rightIndex = clientOrder.indexOf(
        right.client as (typeof clientOrder)[number],
      );
      return (
        (leftIndex === -1 ? fallbackOrder : leftIndex) -
        (rightIndex === -1 ? fallbackOrder : rightIndex)
      );
    }),
  }));
}

export function PlanApplyPage() {
  const statusQuery = useStatusQuery();
  const planQuery = usePlanQuery(statusQuery.data?.initialized === true);
  const applyPlanMutation = useApplyPlanMutation();
  const planData = planQuery.data;

  if (statusQuery.isLoading) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Plan & Apply"
          description="Compute the current ai-sync plan, review the resulting actions, and apply them."
        />
        <p className="text-sm text-muted-foreground">Loading workspace...</p>
      </section>
    );
  }

  if (statusQuery.isError) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Plan & Apply"
          description="Compute the current ai-sync plan, review the resulting actions, and apply them."
        />
        <QueryErrorState message={statusQuery.error.message} />
      </section>
    );
  }

  if (statusQuery.data && !statusQuery.data.initialized) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Plan & Apply"
          description="Compute the current ai-sync plan, review the resulting actions, and apply them."
        />
        <ProjectSetupState workspaceRoot={statusQuery.data.workspace_root} />
      </section>
    );
  }

  if (planQuery.isLoading && !planData) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Plan & Apply"
          description="Compute the current ai-sync plan, review the resulting actions, and apply them."
        />
        <PlanLoadingState />
      </section>
    );
  }

  if (planQuery.isError && !planData) {
    return (
      <section className="space-y-6">
        <PageHeader
          title="Plan & Apply"
          description="Compute the current ai-sync plan, review the resulting actions, and apply them."
        />
        <QueryErrorState message={planQuery.error.message} />
      </section>
    );
  }

  if (!planData) {
    return null;
  }

  const { plan, warnings } = planData;
  const deleteActions = plan.actions.filter(
    (action) => action.action === "delete",
  );
  const groupedActions = groupActionsByArtifact(plan.actions);
  const isRefreshingPlan = planQuery.isFetching && !planQuery.isLoading;

  return (
    <section className="space-y-6">
      <PageHeader
        title="Plan & Apply"
        description="Refresh the plan whenever the manifest changes, then confirm and apply the resulting writes and deletions."
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => void planQuery.refetch()}
              disabled={planQuery.isFetching || applyPlanMutation.isPending}
            >
              <RefreshCwIcon
                className={`size-4 ${planQuery.isFetching ? "animate-spin" : ""}`}
              />
              {planQuery.isFetching ? "Refreshing..." : "Refresh plan"}
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  disabled={
                    applyPlanMutation.isPending ||
                    planQuery.isFetching ||
                    plan.actions.length === 0
                  }
                >
                  Apply plan
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Apply current plan?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {deleteActions.length > 0
                      ? `This plan includes ${deleteActions.length} deletion(s). Review them before continuing.`
                      : "This will execute the current plan against the project files."}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => void applyPlanMutation.mutateAsync()}
                  >
                    Apply now
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </>
        }
      />

      {isRefreshingPlan ? (
        <Alert>
          <RefreshCwIcon className="size-4 animate-spin" />
          <AlertTitle className="flex items-center gap-2">
            Refreshing plan
            <Badge variant="outline">Recomputing</Badge>
          </AlertTitle>
          <AlertDescription>
            Re-reading the manifest and recomputing actions. The current plan
            stays visible until the updated result is ready.
          </AlertDescription>
        </Alert>
      ) : null}

      {planQuery.isError ? (
        <Alert variant="destructive">
          <AlertTriangleIcon className="size-4" />
          <AlertTitle>Could not refresh the plan</AlertTitle>
          <AlertDescription>
            {planQuery.error.message} Showing the last successful plan so you
            can keep reviewing it.
          </AlertDescription>
        </Alert>
      ) : null}

      {warnings.length > 0 ? (
        <Alert variant="warning">
          <AlertTriangleIcon className="size-4" />
          <AlertTitle>Plan warnings</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-5">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 md:grid-cols-3">
        <Card size="sm" className="h-full gap-2">
          <CardHeader className="content-start">
            <CardTitle>Actions</CardTitle>
            <CardDescription className="min-h-10">
              Total planned filesystem mutations.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl leading-none font-semibold">
              {plan.actions.length}
            </p>
          </CardContent>
        </Card>
        <Card size="sm" className="h-full gap-2">
          <CardHeader className="content-start">
            <CardTitle>Sources</CardTitle>
            <CardDescription className="min-h-10">
              Resolved sources in this plan.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl leading-none font-semibold">
              {plan.sources.length}
            </p>
          </CardContent>
        </Card>
        <Card size="sm" className="h-full gap-2">
          <CardHeader className="content-start">
            <CardTitle>Deletes</CardTitle>
            <CardDescription className="min-h-10">
              Destructive actions requiring extra attention.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl leading-none font-semibold">
              {deleteActions.length}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Planned actions</CardTitle>
          <CardDescription>
            {plan.actions.length === 0
              ? "No changes are currently required."
              : "The current plan derived from the manifest and source state."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {plan.actions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No changes detected. The generated outputs already match the
              current manifest.
            </p>
          ) : (
            <div className="space-y-4">
              {groupedActions.map((group) => (
                <div
                  key={`${group.kind}:${group.resource}`}
                  className="rounded-lg border border-border/70"
                >
                  <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-4 py-3">
                    <Badge variant="outline">{group.kind}</Badge>
                    <div className="min-w-0">
                      <p className="font-medium">
                        {group.name || group.resource}
                      </p>
                      {group.name && group.name !== group.resource ? (
                        <p className="text-sm text-muted-foreground">
                          {group.resource}
                        </p>
                      ) : null}
                      {group.description ? (
                        <p className="text-sm text-muted-foreground">
                          {group.description}
                        </p>
                      ) : null}
                    </div>
                  </div>
                  <Table className="table-fixed">
                    <colgroup>
                      <col style={{ width: actionColumnWidth }} />
                      <col style={{ width: clientColumnWidth }} />
                      <col />
                    </colgroup>
                    <TableHeader className="bg-muted/40">
                      <TableRow className="hover:bg-muted/40">
                        <TableHead className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          Action
                        </TableHead>
                        <TableHead className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          Client
                        </TableHead>
                        <TableHead className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          Target
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {group.actions.map((action) => (
                        <TableRow
                          key={`${action.target_key}:${action.client}:${action.action}`}
                        >
                          <TableCell>
                            <Badge variant={actionVariant(action.action)}>
                              {action.action}
                            </Badge>
                          </TableCell>
                          <TableCell className="font-medium">
                            {action.client}
                          </TableCell>
                          <TableCell className="max-w-xl break-all text-muted-foreground">
                            {action.display_target}
                            {action.secret_backed ? (
                              <span className="ml-2 text-xs text-amber-600 dark:text-amber-400">
                                secret
                              </span>
                            ) : null}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

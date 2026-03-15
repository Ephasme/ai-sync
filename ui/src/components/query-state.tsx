import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function QueryErrorState({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>Request failed</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}

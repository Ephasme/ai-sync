import type {
  ManifestSelectionChange,
  ProjectManifestData,
} from "@/api/client";

export function applyManifestChanges(
  manifest: ProjectManifestData,
  changes: ManifestSelectionChange[],
): ProjectManifestData {
  const nextManifest = structuredClone(manifest);

  for (const change of changes) {
    const current = [...(nextManifest[change.section] ?? [])];
    if (change.enabled) {
      if (!current.includes(change.scoped_ref)) {
        current.push(change.scoped_ref);
      }
    } else {
      const filtered = current.filter((item) => item !== change.scoped_ref);
      if (filtered.length === 0) {
        nextManifest[change.section] = [];
        continue;
      }
      nextManifest[change.section] = filtered;
      continue;
    }
    nextManifest[change.section] = current;
  }

  return nextManifest;
}

export function renderManifestPreview(value: unknown, indent = 0): string {
  const spacing = "  ".repeat(indent);

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return `${spacing}[]`;
    }
    return value
      .map((item) => {
        if (
          typeof item === "string" ||
          typeof item === "number" ||
          typeof item === "boolean"
        ) {
          return `${spacing}- ${item}`;
        }
        return `${spacing}-\n${renderManifestPreview(item, indent + 1)}`;
      })
      .join("\n");
  }

  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      return `${spacing}{}`;
    }

    return entries
      .map(([key, child]) => {
        if (Array.isArray(child)) {
          return `${spacing}${key}:\n${renderManifestPreview(child, indent + 1)}`;
        }
        if (child && typeof child === "object") {
          return `${spacing}${key}:\n${renderManifestPreview(child, indent + 1)}`;
        }
        return `${spacing}${key}: ${String(child)}`;
      })
      .join("\n");
  }

  return `${spacing}${String(value)}`;
}

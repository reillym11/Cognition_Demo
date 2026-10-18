import type { ReactElement } from "react";

/** Each tool exports `routes` from web/src/tools/<key>/index.tsx; discovered at build time, no shell edits. */
export type ToolRoute = { path: string; element: ReactElement };

const modules = import.meta.glob<{ routes: ToolRoute[] }>("./*/index.tsx", { eager: true });

export const toolRoutes: ToolRoute[] = Object.values(modules).flatMap((m) => m.routes);

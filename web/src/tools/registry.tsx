import type { ReactElement } from "react";

/** Each tool exports `routes` from web/src/tools/<key>/index.tsx; discovered at build time, no shell edits. */
export type ToolRoute = { path: string; element: ReactElement };

/** Optional home-page content rendered directly below the tile whose nav path matches `below`. */
export type HomeWidget = { below: string; element: ReactElement };

const modules = import.meta.glob<{ routes: ToolRoute[]; homeWidgets?: HomeWidget[] }>("./*/index.tsx", { eager: true });

export const toolRoutes: ToolRoute[] = Object.values(modules).flatMap((m) => m.routes);
export const homeWidgets: HomeWidget[] = Object.values(modules).flatMap((m) => m.homeWidgets ?? []);

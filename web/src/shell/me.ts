import { useQuery } from "@tanstack/react-query";
import { http } from "../api/client";

export type NavEntry = { tool: string; tool_name: string; path: string; label: string };
export type Me = { oid: string; name: string; username: string; roles: string[]; permissions: string[]; region: string | null; nav: NavEntry[] };

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => http<Me>("GET", "/api/me") });
}

export function can(me: Me | undefined, perm: string): boolean {
  return !!me?.permissions.includes(perm);
}

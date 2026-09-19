import { redirect } from "next/navigation";

// `/today` historically rendered the same <Briefing /> surface that `/`
// now lands on. Keeping a second copy meant two routes to maintain for
// one view, so `/today` is preserved only as a redirect for existing
// bookmarks — the briefing lives at `/`.
export default function TodayPage() {
  redirect("/");
}

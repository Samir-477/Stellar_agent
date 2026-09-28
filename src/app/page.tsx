import { redirect } from "next/navigation";
import { currentUser } from "@/lib/session";

// The workspace is private: people start at sign-in and land on Home once signed in.
export default async function Root() {
  redirect((await currentUser()) ? "/home" : "/login");
}

import type { Metadata } from "next";
import { AdminLogin } from "@/components/admin/AdminLogin";

// Not linked from anywhere: our four laptops open /admin once and paste ADMIN_KEY. See lib/admin.ts.
export const metadata: Metadata = { title: "redledger · admin", robots: { index: false, follow: false } };

export default function Page() {
  return <AdminLogin />;
}

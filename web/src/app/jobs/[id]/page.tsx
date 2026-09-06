import { JobView } from "@/components/job-view";
import { SiteHeader } from "@/components/site-header";

interface JobPageProps {
  params: Promise<{ id: string }>;
}

export default async function JobPage({ params }: JobPageProps) {
  const { id } = await params;

  return (
    <div className="job-page">
      <SiteHeader context="Project" actionLabel="New project" />
      <main className="job-main">
        <JobView jobId={id} />
      </main>
    </div>
  );
}

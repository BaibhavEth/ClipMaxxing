import { ClipEditor } from "@/components/clip-editor";
import { SiteHeader } from "@/components/site-header";

interface EditClipPageProps {
  params: Promise<{ id: string; filename: string }>;
}

export default async function EditClipPage({ params }: EditClipPageProps) {
  const { id, filename } = await params;

  return (
    <div className="editor-page">
      <SiteHeader context="Editor" />
      <main className="editor-main">
        <ClipEditor jobId={id} filename={filename} />
      </main>
    </div>
  );
}

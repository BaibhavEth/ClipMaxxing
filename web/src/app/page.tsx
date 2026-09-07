import Image from "next/image";
import Link from "next/link";

import { CloudBackdrop } from "@/components/cloud-backdrop";
import { SiteHeader } from "@/components/site-header";

export default function Home() {
  return (
    <div className="landing-page">
      <CloudBackdrop />
      <SiteHeader action signIn />

      <main>
        <section className="landing-hero">
          <h1>
            Turn long videos into
            <span> clips worth watching.</span>
          </h1>
          <p>
            ClipCraft finds the strongest moments in long-form video and turns them into
            focused, ready-to-share clips without cutting ideas short.
          </p>
          <Link className="landing-primary" href="/create">
            Start clipping
          </Link>
          <p className="landing-note">
            Sign in, add your OpenAI key, and paste a YouTube link. ClipCraft handles the rest.
          </p>
        </section>

        <section className="product-section">
          <div className="product-heading">
            <span>How it works</span>
            <h2>From a YouTube video to finished clips in three steps.</h2>
          </div>

          <div className="walkthrough">
            <article className="workflow-step">
              <div className="workflow-copy">
                <span>Step 1</span>
                <h3>Copy the YouTube link</h3>
                <p>Open the video you want to clip and copy its URL from your browser.</p>
              </div>
              <div className="product-shot">
                <Image
                  src="/step-youtube.jpg"
                  alt="YouTube video page with its URL visible in the browser"
                  width={1024}
                  height={610}
                />
              </div>
            </article>

            <article className="workflow-step workflow-step-reverse">
              <div className="workflow-copy">
                <span>Step 2</span>
                <h3>Choose your output</h3>
                <p>Paste the link, select the number of clips, and set your target length.</p>
              </div>
              <div className="product-shot">
                <Image
                  src="/step-create.png"
                  alt="ClipCraft creation page with URL and clip settings"
                  width={1016}
                  height={675}
                />
              </div>
            </article>

            <article className="workflow-step">
              <div className="workflow-copy">
                <span>Step 3</span>
                <h3>Review and download</h3>
                <p>Play every generated moment, review the context, and download the clips you want.</p>
              </div>
              <div className="product-shot">
                <Image
                  src="/clipcraft-results.png"
                  alt="ClipCraft results showing generated clips with video previews"
                  width={1016}
                  height={635}
                />
              </div>
            </article>
          </div>
        </section>

        <section className="landing-cta">
          <h2>Your next clip is already in the video.</h2>
          <p>Find it without scrubbing through hours of footage.</p>
          <Link className="landing-primary" href="/create">
            Start clipping
          </Link>
        </section>
      </main>

      <footer className="simple-footer">
        <span>ClipCraft</span>
        <p>Only process videos you own or have permission to use.</p>
      </footer>
    </div>
  );
}

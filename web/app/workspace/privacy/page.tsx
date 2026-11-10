import styles from "@/components/workspace/workspace.module.css";

export const metadata = { title: "Workspace privacy" };

export default function WorkspacePrivacyPage() {
  return (
    <div className={styles.stack}>
      <div className={styles.card}>
        <h2>The short version</h2>
        <p className={styles.muted}>
          Your workspace has no account and no password. You can give an email address, but only if you want job alerts;
          without one, ERIO holds nothing that says who you are. Nothing in a workspace is sold or shared.
        </p>
      </div>
      <div className={styles.card}>
        <h3>What ERIO keeps</h3>
        <ul className={styles.list}>
          <li>
            A fingerprint (SHA-256) of a random 256-bit key that lives in your browser. The key itself is never stored on
            ERIO&apos;s servers, so ERIO cannot open your workspace or tell whose it is.
          </li>
          <li>
            The jobs you save (a copy of the title, employer and place, so they still read if the job closes), your stage,
            notes, dates and timeline lines, and your saved searches with their filters.
          </li>
          <li>
            The jobs each saved search found (the latest 100) and, if you add one, your webhook address. A feed address
            is public to whoever you give it to and shows only public job data.
          </li>
          <li>
            If you upload a CV: the list of skills, tools, licences and languages read from it, plus the job titles,
            places and match level you choose. Not the file, not its text.
          </li>
          <li>
            If you ask for email alerts: your address, how often you want them, and the ids of jobs already sent to you
            (so you never get one twice). Nothing is sent until you open the confirmation link; every email has a link
            to pause or delete the address, and deleting the workspace deletes it too. Emails go out through Resend.
          </li>
        </ul>
      </div>
      <div className={styles.card}>
        <h3>What ERIO never keeps</h3>
        <ul className={styles.list}>
          <li>
            Your CV file or its text. An uploaded or pasted CV is read for skills in that one request and discarded; it is
            not saved or logged. If you tick “keep my CV” on the paste page, the text stays in this browser only.
          </li>
          <li>Your name, home address, device or location. ERIO sets no tracking cookie for the workspace.</li>
          <li>
            Applications are never sent for you. ERIO has no way to apply on your behalf; the apply kit is text you copy.
          </li>
        </ul>
      </div>
      <div className={styles.card}>
        <h3>Your control</h3>
        <ul className={styles.list}>
          <li>Export everything as a JSON file, or delete everything in one click, in Settings.</li>
          <li>The workspace link keeps its key after the # sign, which browsers never send to any server.</li>
          <li>A workspace nobody has used for 12 months is deleted automatically, with everything in it.</li>
          <li>
            A webhook receives the new matches of one search as JSON and nothing about you. ERIO only sends to public
            https addresses and ignores the reply.
          </li>
        </ul>
      </div>
    </div>
  );
}

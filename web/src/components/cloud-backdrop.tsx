"use client";

import { motion } from "motion/react";

export function CloudBackdrop() {
  return (
    <div className="cloud-backdrop" aria-hidden="true">
      <motion.div
        className="soft-cloud soft-cloud-one"
        animate={{ x: [0, 30, 0], y: [0, -8, 0] }}
        transition={{ duration: 24, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="soft-cloud soft-cloud-two"
        animate={{ x: [0, -38, 0], y: [0, 8, 0] }}
        transition={{ duration: 30, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}

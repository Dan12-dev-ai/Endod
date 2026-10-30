"use client";

import * as React from "react";
import { Drawer as DrawerPrimitive } from "vaul";

const Drawer = ({ shouldScaleBackground = true, direction = "bottom", ...props }: React.ComponentProps<typeof DrawerPrimitive.Root> & { direction?: "top" | "bottom" | "left" | "right" }) => (
  <DrawerPrimitive.Root direction={direction} shouldScaleBackground={shouldScaleBackground} {...props} />
);
Drawer.displayName = "Drawer";

const DrawerTrigger = DrawerPrimitive.Trigger;
const DrawerPortal = DrawerPrimitive.Portal;
const DrawerClose = DrawerPrimitive.Close;

const DrawerOverlay = React.forwardRef<
  React.ElementRef<typeof DrawerPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DrawerPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DrawerPrimitive.Overlay ref={ref} className={"fixed inset-0 z-50 bg-black/80 " + (className || "")} {...props} />
));
DrawerOverlay.displayName = DrawerPrimitive.Overlay.displayName;

const DrawerContent = React.forwardRef<
  React.ElementRef<typeof DrawerPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DrawerPrimitive.Content> & { direction?: "top" | "bottom" | "left" | "right" }
>(({ className, children, direction = "bottom", ...props }, ref) => {
  const classes =
    direction === "right"
      ? "fixed inset-y-0 right-0 z-50 h-full w-[80vw] sm:w-[85vw] max-w-sm sm:max-w-md flex flex-col overflow-y-auto border-l bg-white dark:bg-gray-800 " + (className || "")
      : "fixed inset-x-0 bottom-0 z-50 mt-24 flex h-auto max-h-[85vh] flex-col overflow-y-auto rounded-t-[10px] border bg-white dark:bg-gray-800 " + (className || "");
  return (
    <DrawerPortal>
      <DrawerOverlay />
      <DrawerPrimitive.Content ref={ref} className={classes} {...props}>
        {direction === "bottom" && <div className="mx-auto mt-4 h-2 w-[100px] rounded-full bg-muted" />}
        {children}
      </DrawerPrimitive.Content>
    </DrawerPortal>
  );
});
DrawerContent.displayName = DrawerPrimitive.Content.displayName;

const DrawerHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={"grid gap-1.5 p-4 text-center sm:text-left " + (className || "")} {...props} />
);
DrawerHeader.displayName = "DrawerHeader";

const DrawerTitle = React.forwardRef<
  React.ElementRef<typeof DrawerPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DrawerPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DrawerPrimitive.Title ref={ref} className={"text-lg font-semibold leading-none tracking-tight " + (className || "")} {...props} />
));
DrawerTitle.displayName = DrawerPrimitive.Title.displayName;

export { Drawer, DrawerPortal, DrawerOverlay, DrawerTrigger, DrawerClose, DrawerContent, DrawerHeader, DrawerTitle };

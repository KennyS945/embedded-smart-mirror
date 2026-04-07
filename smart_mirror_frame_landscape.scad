// ============================================================
//  SMART MIRROR FRAME  –  4-piece snap-together  (LANDSCAPE)
//
//  Monitor : 19" x 11" x 1"
//    MON_W = 482.6 mm  (long/width side, X axis)  ← was MON_H
//    MON_H = 279.4 mm  (short/height side, Z axis) ← was MON_W
//    MON_D =  25.4 mm  (depth, Y axis)
//
//  Landscape layout:
//    TOP & BOTTOM rails = LONG  (span MON_W + 2*WALL in X)
//    LEFT & RIGHT rails = SHORT (span MON_H in Z)
//
//  ── SNAP JOINT DESIGN ────────────────────────────────────────
//
//  Dovetail tabs on side rails protrude in ±Z.
//  Long rails (top/bottom) receive sockets cut into their X end faces.
//  Same joint geometry as portrait version — just longer rails.
//
//  ── CAMERA : Logitech Brio 105 / C505 (1080p USB) ───────────
//
//  Physical measurements (from product images):
//    Body  : ~95 mm wide × ~35 mm tall × ~30 mm deep
//            (horizontal pill-shaped housing)
//    Clip  : ~28 mm wide × ~40 mm tall
//    Lens aperture : ~10 mm diameter
//
//  Embedded in TOP long rail, centred horizontally.
//  Lens faces front (Y=0). Cable exits rear of bump-out.
//
//  ── WIRE MANAGEMENT ─────────────────────────────────────────
//
//  TOP rail:    camera USB cable channel through bump-out back wall
//  BOTTOM rail: monitor power + video cable channel (rear of rail)
//               sized for 2× cables side by side (HDMI + power)
//
//  PARTS:
//    "top"    long top rail with embedded Logitech camera
//    "bottom" long bottom rail with rear cable channel
//    "left"   short side rail (print 2)
//    "right"  alias for left
//    "all"    exploded view
// ============================================================

PART = "all";

// ----------------------------------------------------------
//  MONITOR  (landscape orientation)
// ----------------------------------------------------------
MON_W = 482.6;   // long dimension → now the horizontal width
MON_H = 279.4;   // short dimension → now the vertical height
MON_D =  25.4;

// ----------------------------------------------------------
//  FRAME PROFILE
// ----------------------------------------------------------
WALL   =  6;
LIP    =  8;
REVEAL =  4;
DEPTH  = MON_D + WALL;    // ≈ 31.4 mm

// ----------------------------------------------------------
//  DOVETAIL
// ----------------------------------------------------------
TAB_W  = 16;
TAB_H  = 10;
TAB_T  = DEPTH - 2;       // ≈ 29.4 mm
DRAFT  =  2;
CLEAR  =  0.3;

// ----------------------------------------------------------
//  CAMERA  (Logitech 1080p – landscape body)
//
//  The camera sits horizontally in the top rail.
//  Body is a horizontal pill: wide in X, shallow in Z.
//    CAM_BL = body length (X) = 95 mm
//    CAM_BW = body width  (Y, front-to-back) = 30 mm
//    CAM_BH = body height (Z) = 35 mm
//  Clip sits below the body (toward monitor):
//    CAM_CL = clip width (X) = 28 mm
//    CAM_CW = clip width (Y) = 20 mm
//    CAM_CH = clip height (Z) = 40 mm
// ----------------------------------------------------------
CAM_BL  = 95.0;    // body X (wide axis)
CAM_BW  = 30.0;    // body Y (depth into rail)
CAM_BH  = 35.0;    // body Z (height)
CAM_CL  = 28.0;    // clip/stand X
CAM_CW  = 20.0;    // clip/stand Y
CAM_CH  = 40.0;    // clip/stand Z (hangs down below body)
CAM_CLR =  0.5;    // pocket clearance all around
LENS_D  = 12.0;    // lens aperture diameter
USB_W   =  9.0;    // USB-A cable cross section (square approx)

// ----------------------------------------------------------
//  WIRE MANAGEMENT (bottom rail)
//
//  Two channels side by side on the rear face of the bottom
//  rail for monitor power + video cable routing.
//  Channels are open slots cut into the rear top edge.
// ----------------------------------------------------------
WIRE_W  = 12.0;    // individual channel width (fits HDMI + power)
WIRE_H  = 14.0;    // channel height
WIRE_SEP = 6.0;    // gap between the two channels

// ----------------------------------------------------------
//  RAIL HEIGHTS
// ----------------------------------------------------------
SHORT_H    = WALL + LIP + REVEAL;                 // 18 mm  (side rails)
TOP_RAIL_H = CAM_CH + CAM_BH + 2*WALL;           // clip below + body + walls
                                                   // = 40+35+12 = 87 mm

// Bump-out (rear protrusion to fully enclose camera body)
BUMP_D = 8;
BUMP_W = CAM_BL + 2*WALL;
BUMP_H = CAM_BH + 2*WALL;

// ============================================================
//  dovetail_tab
// ============================================================
module dovetail_tab() {
    linear_extrude(TAB_T, center=true)
    polygon([
        [ 0,      -(TAB_W/2)       ],
        [ 0,       (TAB_W/2)       ],
        [ TAB_H,   (TAB_W/2-DRAFT) ],
        [ TAB_H,  -(TAB_W/2-DRAFT) ]
    ]);
}

// ============================================================
//  dovetail_socket
// ============================================================
module dovetail_socket() {
    c = CLEAR;
    linear_extrude(TAB_T + 2*c, center=true)
    polygon([
        [-0.5,       -(TAB_W/2 + c)        ],
        [-0.5,        (TAB_W/2 + c)        ],
        [ TAB_H+0.5,  (TAB_W/2-DRAFT + c)  ],
        [ TAB_H+0.5, -(TAB_W/2-DRAFT + c)  ]
    ]);
}

// ============================================================
//  TOP RAIL  (long, camera embedded, USB cable channel)
//
//  X = 0 … MON_W + 2*WALL  (long axis, ~494.6 mm)
//  Y = 0 (front) … DEPTH (rear)
//  Z = 0 (bottom/inner) … TOP_RAIL_H (top/outer)
//
//  Camera centred at X = L/2.
//  Camera clip pocket starts at Z=WALL (above monitor slot wall).
//  Camera body pocket sits on top of clip pocket.
//  Lens port cut through front face (Y=0).
//  Bump-out extends rearward from Y=DEPTH for BUMP_D.
//  USB cable channel exits through bump-out back wall, centred on camera.
// ============================================================
module top_rail() {
    L      = MON_W + 2*WALL;
    sock_z = TAB_W/2 + CLEAR;   // 8.3 mm — socket centre from bottom

    cx = L / 2;   // camera centre X

    // Clip pocket (lower, narrower)
    cl_x0 = cx - (CAM_CL + 2*CAM_CLR) / 2;
    cl_y0 = (DEPTH - (CAM_CW + 2*CAM_CLR)) / 2;
    cl_z0 = WALL;

    // Body pocket (upper, wider, sits on top of clip)
    bo_x0 = cx - (CAM_BL + 2*CAM_CLR) / 2;
    bo_y0 = (DEPTH - (CAM_BW + 2*CAM_CLR)) / 2;
    bo_z0 = cl_z0 + CAM_CH + 2*CAM_CLR;

    // Lens port Z centre (middle of body pocket)
    lens_z = bo_z0 + (CAM_BH + 2*CAM_CLR) / 2;

    // Bump-out position
    bump_x0 = cx - BUMP_W / 2;
    bump_z0 = cl_z0;   // starts at same Z as clip pocket

    difference() {
        union() {
            // ── main rail body ─────────────────────────────
            cube([L, DEPTH, TOP_RAIL_H]);

            // ── rear bump-out housing ──────────────────────
            translate([bump_x0, DEPTH, bump_z0])
            cube([BUMP_W, BUMP_D, BUMP_H]);
        }

        // ── monitor slot – bottom face (Z=0) ───────────────
        translate([WALL, REVEAL, -0.1])
        cube([MON_W, LIP + WALL + 0.1, WALL + 0.2]);

        // ── dovetail socket – left end ──────────────────────
        translate([0, DEPTH/2, sock_z])
        rotate([-90, 180, 0])
        dovetail_socket();

        // ── dovetail socket – right end ─────────────────────
        translate([L, DEPTH/2, sock_z])
        rotate([90, 0, 0])
        dovetail_socket();

        // ── camera clip pocket ───────────────────────────────
        //    Clip hangs down into the rail from body-level down.
        translate([cl_x0, cl_y0, cl_z0])
        cube([CAM_CL + 2*CAM_CLR,
              CAM_CW + 2*CAM_CLR,
              CAM_CH + 2*CAM_CLR]);

        // ── camera body pocket ───────────────────────────────
        translate([bo_x0, bo_y0, bo_z0])
        cube([CAM_BL + 2*CAM_CLR,
              CAM_BW + 2*CAM_CLR,
              CAM_BH + 2*CAM_CLR]);

        // ── lens port – front face (Y=0) ────────────────────
        translate([cx, -0.1, lens_z])
        rotate([-90, 0, 0])
        cylinder(h=WALL + 1, r=LENS_D/2, $fn=64);

        // ── top access slot (drop-in installation) ───────────
        translate([bo_x0, bo_y0, TOP_RAIL_H - 0.1])
        cube([CAM_BL + 2*CAM_CLR,
              CAM_BW + 2*CAM_CLR,
              WALL + 0.2]);

        // ── USB cable channel – exits bump-out back wall ─────
        //    Centred in X; runs from body cavity through back wall.
        translate([(L - USB_W) / 2,
                   DEPTH + BUMP_D - WALL - 0.1,
                   bo_z0])
        cube([USB_W, WALL + 0.2, USB_W]);
    }
}

// ============================================================
//  BOTTOM RAIL  (long, wire management channels)
//
//  X = 0 … MON_W + 2*WALL
//  Y = 0 (front) … DEPTH (rear)
//  Z = 0 (inner/bottom) … SHORT_H (outer/top, 18 mm)
//
//  Monitor slot opens on top face (Z = SHORT_H).
//
//  Wire channels: two U-shaped slots cut into the rear face
//  (Y=DEPTH) and open at the bottom (Z=0).
//  Positioned near centre-bottom of the rail for tidy cable
//  drop to a Raspberry Pi / media player below the mirror.
//
//  The monitor's HDMI and power cables (visible in reference
//  photo) exit the bottom of the monitor and are routed down
//  through these channels.
// ============================================================
module bottom_rail() {
    L      = MON_W + 2*WALL;
    sock_z = SHORT_H - TAB_W/2 - CLEAR;   // 9.7 mm

    // Two channels, centred together on the rail length
    total_chan_w = 2*WIRE_W + WIRE_SEP;
    ch_x0 = L/2 - total_chan_w/2;   // left edge of left channel

    difference() {
        cube([L, DEPTH, SHORT_H]);

        // ── monitor slot – top face ─────────────────────────
        translate([WALL, REVEAL, SHORT_H - WALL - 0.1])
        cube([MON_W, LIP + WALL + 0.1, WALL + 0.2]);

        // ── dovetail socket – left end ──────────────────────
        translate([0, DEPTH/2, sock_z])
        rotate([-90, 180, 0])
        dovetail_socket();

        // ── dovetail socket – right end ─────────────────────
        translate([L, DEPTH/2, sock_z])
        rotate([90, 0, 0])
        dovetail_socket();

        // ── wire channel 1 (left / power cable) ────────────
        //    Open slot: exits through bottom (Z=0) and rear (Y=DEPTH).
        //    U-shaped groove in the rear portion of the rail.
        translate([ch_x0,
                   DEPTH - WIRE_W - WALL,
                   -0.1])
        cube([WIRE_W, WIRE_W + WALL + 0.1, WIRE_H + 0.1]);

        // ── wire channel 1 rear opening ─────────────────────
        translate([ch_x0,
                   DEPTH - WIRE_W - WALL - 0.1,
                   -0.1])
        cube([WIRE_W, WALL + 0.2, WIRE_H + 0.1]);

        // ── wire channel 2 (right / video cable) ────────────
        translate([ch_x0 + WIRE_W + WIRE_SEP,
                   DEPTH - WIRE_W - WALL,
                   -0.1])
        cube([WIRE_W, WIRE_W + WALL + 0.1, WIRE_H + 0.1]);

        // ── wire channel 2 rear opening ─────────────────────
        translate([ch_x0 + WIRE_W + WIRE_SEP,
                   DEPTH - WIRE_W - WALL - 0.1,
                   -0.1])
        cube([WIRE_W, WALL + 0.2, WIRE_H + 0.1]);
    }
}

// ============================================================
//  SIDE RAIL  (short – left or right, print 2)
//
//  X = width (0 … RW = WALL+LIP+REVEAL = 18 mm)
//  Y = depth (0 = front … DEPTH)
//  Z = height (0 … MON_H = 279.4 mm)  ← short dimension now
//
//  Monitor slot: interior face (X = RW)
//  Tabs:
//    Top end    (Z=MON_H): rotate([0,-90,-90])
//    Bottom end (Z=0):     rotate([0, 90,-90])
// ============================================================
module side_rail() {
    RW = WALL + LIP + REVEAL;

    difference() {
        union() {
            cube([RW, DEPTH, MON_H]);

            // tab – top end (+Z)
            translate([RW/2, DEPTH/2, MON_H])
            rotate([0, -90, -90])
            dovetail_tab();

            // tab – bottom end (-Z)
            translate([RW/2, DEPTH/2, 0])
            rotate([0, 90, -90])
            dovetail_tab();
        }

        // monitor slot – interior face
        translate([REVEAL, REVEAL, -0.1])
        cube([LIP + WALL + 0.1, DEPTH - REVEAL, MON_H + 0.2]);
    }
}

// ============================================================
//  EXPLODED VIEW
// ============================================================
module all_parts() {
    g  = 50;
    RW = WALL + LIP + REVEAL;

    // Top rail floated above
    color("SteelBlue")
    translate([0, 0, MON_H + g])
    top_rail();

    // Bottom rail below
    color("SteelBlue")
    translate([0, 0, -(SHORT_H + g)])
    bottom_rail();

    // Left side rail
    color("SlateGray")
    translate([-(RW + g), 0, 0])
    side_rail();

    // Right side rail
    color("SlateGray")
    translate([MON_W + 2*WALL + g, 0, 0])
    side_rail();
}

// ============================================================
//  RENDER
// ============================================================
if      (PART == "top")    top_rail();
else if (PART == "bottom") bottom_rail();
else if (PART == "left")   side_rail();
else if (PART == "right")  side_rail();
else                       all_parts();

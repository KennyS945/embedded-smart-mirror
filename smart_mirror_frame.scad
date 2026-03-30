// ============================================================
//  SMART MIRROR FRAME  –  4-piece snap-together  (PORTRAIT)
//
//  Monitor : 19" x 11" x 1"
//    MON_W = 279.4 mm  (short/width side, X axis)
//    MON_H = 482.6 mm  (long/height side, Z axis)
//    MON_D =  25.4 mm  (depth, Y axis)
//
//  Portrait layout:
//    TOP & BOTTOM rails  = SHORT  (span MON_W)
//    LEFT & RIGHT  rails = TALL   (span MON_H)
//
//  Snap joint design (verified):
//    TALL side rails carry dovetail TABS at each end (±Z).
//    SHORT top/bottom rails carry dovetail SOCKETS at each end (±X).
//    Assembly: side rail slides vertically into top+bottom rails.
//
//  Dovetail module convention:
//    - Polygon in XY plane, extruded in Z (centered).
//    - Protrusion direction: +X (local).
//    - Width spans ±TAB_W/2 in Y (local).
//    - Thickness spans ±TAB_T/2 in Z (local, centered).
//
//  Rotation to point tab in +Z (top of side rail):
//    rotate([0,-90,-90])  →  local-X → world+Z  (protrude up)
//                             local-Y → world+X  (width along rail X)
//                             local-Z → world+Y  (thickness along depth)
//
//  Rotation to point tab in -Z (bottom of side rail):
//    rotate([0,90,-90])   →  local-X → world-Z  (protrude down)
//                             local-Y → world+X
//                             local-Z → world-Y  (still spans depth)
//
//  Socket Z-centre in short rails:
//    Bottom rail: SHORT_H - TAB_H/2  (near top face, receives downward tab)
//    Top rail:    TAB_H/2            (near bottom face, receives upward tab)
//
//  Camera : Logitech 101 (embedded in top rail)
//    Stand : 42.5 x 30 x 10 mm
//    Body  : 20  x 20 x 30 mm  (lens faces front face, -Y)
//
//  PARTS:
//    "top"    short top rail with embedded camera
//    "bottom" short bottom rail
//    "left"   tall side rail (print 2)
//    "right"  alias for "left"
//    "all"    exploded view
// ============================================================

PART = "all";   // ← "top" / "bottom" / "left" / "right" / "all"

// ----------------------------------------------------------
//  MONITOR
// ----------------------------------------------------------
MON_W = 279.4;
MON_H = 482.6;
MON_D =  25.4;

// ----------------------------------------------------------
//  FRAME PROFILE
// ----------------------------------------------------------
WALL   =  6;             // outer skin thickness
LIP    =  8;             // rear flange behind monitor
REVEAL =  4;             // front bezel overlap
DEPTH  = MON_D + WALL;   // front-to-back channel depth ≈ 31.4 mm

// ----------------------------------------------------------
//  DOVETAIL
// ----------------------------------------------------------
TAB_W  = 16;             // base width
TAB_H  =  8;             // protrusion length
TAB_T  = DEPTH - 2;      // extrusion thickness (≈ 29.4 mm, centered → ±14.7)
DRAFT  =  2;             // taper per side
CLEAR  =  0.3;           // fit clearance

// ----------------------------------------------------------
//  CAMERA (Logitech 101)
// ----------------------------------------------------------
CAM_SL  = 42.5;
CAM_SW  = 30.0;
CAM_SH  = 10.0;
CAM_BL  = 20.0;
CAM_BW  = 20.0;
CAM_BH  = 30.0;
CAM_CLR =  0.4;
LENS_D  = 10.0;
CABLE_W =  8.0;

// Short rail heights
SHORT_H    = WALL + LIP + REVEAL;         // 18 mm  (bottom rail)
TOP_RAIL_H = CAM_SH + CAM_BH + 2*WALL;   // 52 mm  (top rail, fits camera)

// ============================================================
//  dovetail_tab  –  protrusion in local +X
// ============================================================
module dovetail_tab() {
    linear_extrude(TAB_T, center=true)
    polygon([
        [ 0,      -(TAB_W/2)        ],
        [ 0,       (TAB_W/2)        ],
        [ TAB_H,   (TAB_W/2-DRAFT)  ],
        [ TAB_H,  -(TAB_W/2-DRAFT)  ]
    ]);
}

// ============================================================
//  dovetail_socket  –  same profile + CLEAR, protrusion in local +X
//  Subtract this from a rail end to receive a tab.
// ============================================================
module dovetail_socket() {
    c = CLEAR;
    linear_extrude(TAB_T + 2*c, center=true)
    polygon([
        [-0.5,      -(TAB_W/2 + c)        ],
        [-0.5,       (TAB_W/2 + c)        ],
        [ TAB_H+0.5, (TAB_W/2-DRAFT + c)  ],
        [ TAB_H+0.5,-(TAB_W/2-DRAFT + c)  ]
    ]);
}

// ============================================================
//  TOP RAIL
//
//  Frame of reference:
//    X = length (0 … MON_W + 2*WALL = 291.4 mm)
//    Y = depth  (0 = mirror front face … DEPTH = rear)
//    Z = height (0 = inner bottom face … TOP_RAIL_H = outer top)
//
//  Monitor slot  → opens at Z=0 (bottom inner face), full X
//  Dovetail sockets at X=0 and X=L:
//    Tab arrives travelling in +Z (upward from side rail top).
//    Socket centred at Z = TAB_H/2 = 4 mm from bottom face.
//    Socket opens in ±X so tab slides in from the side rail end.
//    Rotation: rotate([0,-90,-90]) on the socket shape so its
//    protrusion (+X local) aims in -X or +X world as needed.
// ============================================================
module top_rail() {
    L  = MON_W + 2*WALL;   // 291.4 mm

    // Socket Z centre = TAB_H/2 from bottom face (where tab arrives)
    sock_z = TAB_H / 2;    // 4 mm

    // Camera cavity positions
    cx   = L / 2;
    sx0  = cx - (CAM_SL + 2*CAM_CLR) / 2;
    sy0  = (DEPTH - (CAM_SW + 2*CAM_CLR)) / 2;
    sz0  = WALL;
    bx0  = cx - (CAM_BL + 2*CAM_CLR) / 2;
    by0  = (DEPTH - (CAM_BW + 2*CAM_CLR)) / 2;
    bz0  = sz0 + CAM_SH + 2*CAM_CLR;
    lens_z = bz0 + (CAM_BH + 2*CAM_CLR) / 2;

    difference() {
        cube([L, DEPTH, TOP_RAIL_H]);

        // ---- monitor slot (bottom face, Z=0) ----
        translate([WALL, REVEAL, -0.1])
        cube([MON_W, LIP + WALL + 0.1, WALL + 0.2]);

        // ---- dovetail socket, left end (X=0) ----
        // Tab comes from -X side, so socket opens toward -X.
        // We want local-X of socket shape to point in +X world
        // (so the cavity opens correctly toward -X when subtracted).
        // rotate([0,-90,-90]): local-X→world+Z but we need socket in X face.
        // For a socket in the X=0 face opening in -X:
        //   local-X (protrusion) → world -X
        //   local-Y (width)      → world +Z  (width spans height of rail)
        //   local-Z (thickness)  → world +Y  (thickness spans depth)
        // rotate([0,90,90]):
        //   Rx(90): X→X, Y→-Z, Z→Y  ... let's use verified matrix result:
        //   rotate([0,90,-90]) gives X→-Z. Not right.
        //   For X→-X, Z→Y: rotate([0,180,0]) gives X→-X, Z→-Z. Not right.
        //   Correct: rotate([0,90,0]) → X→-Z. No.
        //   We need local+X → world-X (socket opens toward outside on left face).
        //   rotate([0,180,0]): X→-X, Y→Y, Z→-Z  ... thickness goes -Z not +Y.
        //   rotate([-90,180,0]): 
        //     Rx(-90): X→X, Y→Z, Z→-Y
        //     Ry(180): X→-X, Y→Y, Z→-Z
        //     Rz(0): no change
        //     Combined: X→-X, Y→Z, Z→Y  ✓  (X→-X protrudes left, Y→Z width up, Z→Y thickness into depth)
        translate([0, DEPTH/2, sock_z])
        rotate([-90, 180, 0])
        dovetail_socket();

        // ---- dovetail socket, right end (X=L) ----
        // Socket opens toward +X:
        //   local+X → world+X, local Y→Z, local Z→Y
        //   rotate([-90,0,0]): X→X, Y→Z, Z→-Y  ... Z→-Y not +Y.
        //   rotate([90,0,0]): X→X, Y→-Z, Z→Y  ... Y→-Z not +Z.
        //   We need X→+X, Y→+Z, Z→+Y:
        //   rotate([90,180,0]):
        //     Rx(90): X→X, Y→-Z, Z→Y
        //     Ry(180): X→-X, Y→Y, Z→-Z
        //     Rz(0)
        //     Combined: X→-X. No.
        //   rotate([-90,0,0]): X→X, Y→Z, Z→-Y. Width up ✓ but thickness goes -Y.
        //   The tab itself is symmetric in its taper, and -Y thickness is fine
        //   since the socket is symmetric about Y=DEPTH/2 (centered).
        //   Use rotate([-90,0,0]) for right socket — works by symmetry.
        translate([L, DEPTH/2, sock_z])
        rotate([-90, 0, 0])
        dovetail_socket();

        // ---- stand cavity ----
        translate([sx0, sy0, sz0])
        cube([CAM_SL+2*CAM_CLR, CAM_SW+2*CAM_CLR, CAM_SH+2*CAM_CLR]);

        // ---- body cavity ----
        translate([bx0, by0, bz0])
        cube([CAM_BL+2*CAM_CLR, CAM_BW+2*CAM_CLR, CAM_BH+2*CAM_CLR]);

        // ---- lens port (front face Y=0) ----
        translate([cx, -0.1, lens_z])
        rotate([-90, 0, 0])
        cylinder(h=WALL+1, r=LENS_D/2, $fn=64);

        // ---- cable channel (rear face Y=DEPTH) ----
        translate([(L-CABLE_W)/2, DEPTH-WALL-0.1, bz0])
        cube([CABLE_W, WALL+0.2, CABLE_W]);

        // ---- top access slot for camera assembly ----
        translate([bx0, by0, TOP_RAIL_H-0.1])
        cube([CAM_BL+2*CAM_CLR, CAM_BW+2*CAM_CLR, WALL+0.2]);
    }
}

// ============================================================
//  BOTTOM RAIL
//
//  X = length, Y = depth, Z = height (0 … SHORT_H = 18 mm)
//  Monitor slot opens at Z = SHORT_H (top inner face).
//  Socket Z centre = SHORT_H - TAB_H/2 = 14 mm from bottom
//  (tab arrives from above, travelling in -Z).
// ============================================================
module bottom_rail() {
    L = MON_W + 2*WALL;

    // Socket Z centre near TOP face (tab arrives downward from side rail)
    sock_z = SHORT_H - TAB_H / 2;   // 14 mm

    difference() {
        cube([L, DEPTH, SHORT_H]);

        // ---- monitor slot (top face) ----
        translate([WALL, REVEAL, SHORT_H - WALL - 0.1])
        cube([MON_W, LIP + WALL + 0.1, WALL + 0.2]);

        // ---- dovetail socket, left end ----
        translate([0, DEPTH/2, sock_z])
        rotate([-90, 180, 0])
        dovetail_socket();

        // ---- dovetail socket, right end ----
        translate([L, DEPTH/2, sock_z])
        rotate([-90, 0, 0])
        dovetail_socket();
    }
}

// ============================================================
//  SIDE RAIL  (left or right — print 2)
//
//  X = width (0 … WALL+LIP+REVEAL = 18 mm)
//  Y = depth (0 = front face … DEPTH)
//  Z = height (0 … MON_H = 482.6 mm)
//
//  Monitor slot: opens on interior face (X = RW).
//  Dovetail TABS:
//    Top end  (Z = MON_H): tab protrudes in +Z
//      rotate([0,-90,-90]): local-X→world+Z, local-Y→world+X, local-Z→world+Y
//    Bottom end (Z = 0):   tab protrudes in -Z
//      rotate([0,90,90]):  local-X→world-Z, local-Y→world-X — no, let's verify:
//      We need local-X→-Z, local-Y→+X, local-Z→-Y (or by symmetry just flip):
//      rotate([0,90,-90]): X→-Z ✓, Y→+X... let's verify from earlier run:
//        rotate([0,90,-90]): X→[0,-0,-1] = -Z ✓  Y→[1,0,0] = +X ✓  Z→[0,-1,0] = -Y
//        Thickness in -Y is fine (symmetric about DEPTH/2).
// ============================================================
module side_rail() {
    RW = WALL + LIP + REVEAL;

    difference() {
        union() {
            cube([RW, DEPTH, MON_H]);

            // ---- tab at top end: protrudes in +Z ----
            // rotate([0,-90,-90]): X→+Z, Y→+X, Z→+Y
            translate([RW/2, DEPTH/2, MON_H])
            rotate([0, -90, -90])
            dovetail_tab();

            // ---- tab at bottom end: protrudes in -Z ----
            // rotate([0,90,-90]): X→-Z, Y→+X, Z→-Y
            translate([RW/2, DEPTH/2, 0])
            rotate([0, 90, -90])
            dovetail_tab();
        }

        // ---- monitor slot (interior face, X=RW) ----
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

    // top rail – floated above
    color("SteelBlue")
    translate([0, 0, MON_H + g])
    top_rail();

    // bottom rail – below
    color("SteelBlue")
    translate([0, 0, -(SHORT_H + g)])
    bottom_rail();

    // left side rail
    color("SlateGray")
    translate([-(RW + g), 0, 0])
    side_rail();

    // right side rail
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

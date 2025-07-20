#include <camera/camera_api.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

camera_handle_t camera;
FILE *video_file;

int frame_callback(camera_buffer_t *buf, void *arg) {
    if (buf->frametype != CAMERA_FRAMETYPE_VIDEO) return 0;

    if (video_file && buf->framebuf && buf->framedesc.size > 0) {
        fwrite(buf->framebuf, 1, buf->framedesc.size, video_file);
    }

    return 0;
}

int main() {
    camera_error_t err;

    // Open default camera
    err = camera_open(CAMERA_UNIT_CAMERA, 0, &camera);
    if (err != CAMERA_EOK) {
        fprintf(stderr, "camera_open failed: %d\n", err);
        return 1;
    }

    // Set video format (modify as needed)
    camera_set_video_property_i(camera, CAMERA_IMGPROP_WIDTH, 640);
    camera_set_video_property_i(camera, CAMERA_IMGPROP_HEIGHT, 480);
    camera_set_video_property_i(camera, CAMERA_IMGPROP_FORMAT, CAMERA_FRAMETYPE_NV12);

    // Open output file
    video_file = fopen("/tmp/output.yuv", "wb");
    if (!video_file) {
        perror("fopen");
        camera_close(camera);
        return 1;
    }

    // Start streaming and register callback
    camera_register_callback(camera, frame_callback, NULL);
    camera_start_video(camera);

    printf("Recording... Press Ctrl+C to stop.\n");
    pause(); // Wait forever

    // Cleanup
    camera_stop_video(camera);
    camera_close(camera);
    fclose(video_file);

    return 0;
}

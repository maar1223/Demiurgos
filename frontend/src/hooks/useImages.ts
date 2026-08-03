import { useCallback, useState } from "react";
import useSWR from "swr";
import { listImages, uploadImage, deleteImage } from "@/api/wiki";
import type { ImageInfo, MediaList } from "@/api/types";

/**
 * Build the SWR key for a world's image list.
 */
function imagesKey(mundo: string | undefined): string | null {
  return mundo ? `images-${mundo}` : null;
}

/**
 * Fetches the list of images for a given world via SWR.
 * Auto-refetches on mount and window focus.
 */
export function useImages(mundo: string) {
  const {
    data,
    error,
    isLoading,
    isValidating,
    mutate,
  } = useSWR<MediaList, Error>(imagesKey(mundo), () => listImages(mundo), {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });

  return {
    images: data?.images ?? ([] as ImageInfo[]),
    total: data?.total ?? 0,
    isLoading,
    isValidating,
    error,
    mutate,
  };
}

/**
 * Provides an upload function and tracks upload state.
 * Returns `{ upload, isUploading, uploadError }`.
 * Call `upload(file, overwrite?)` to upload an image.
 */
export function useImageUpload(mundo: string) {
  const { mutate } = useImages(mundo);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<Error | null>(null);

  const upload = useCallback(
    async (file: File, overwrite?: boolean) => {
      setIsUploading(true);
      setUploadError(null);
      try {
        const result = await uploadImage(mundo, file, overwrite);
        // Revalidate the image list after upload
        await mutate();
        return result;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setUploadError(error);
        throw error;
      } finally {
        setIsUploading(false);
      }
    },
    [mundo, mutate],
  );

  return { upload, isUploading, uploadError };
}

/**
 * Provides a delete function for images.
 * Call `remove(path)` to delete an image.
 */
export function useImageDelete(mundo: string) {
  const { mutate } = useImages(mundo);

  const remove = useCallback(
    async (path: string) => {
      const result = await deleteImage(mundo, path);
      await mutate();
      return result;
    },
    [mundo, mutate],
  );

  return { remove };
}
